"""Plain matcher/mailbox linkage for the enclave-plane wire shape.

This is intentionally a stand-in implementation. It proves the P0/P2/P3
interfaces with ordinary Python objects while keeping the transport unchanged:
the matcher returns opaque handles, and only the mailbox resolves those handles
to reachability records and routing keys.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterator, Mapping, Sequence

from .config import PeerAddressConfig, TrustedReachabilityRelayConfig
from .directory import DiscoveryRequest, DiscoveryResult, PeerRecord
from .expert_route import PeerCandidate
from .handles import (
    HandleResolution,
    OpaqueHandle,
    OpaqueHandleIssuer,
    OpaqueHandleRecord,
)
from .memory_index import MemoryManifest, score_manifest
from .oblivious import DUMMY_INDEX, oblivious_top_k
from .peer_address import ROUTE_RELAY, build_dial_plan, peer_address_record_from_dict
from .transport_dial import DialTarget, resolve_dial_target


PLAIN_MATCHER_V1 = "plain_matcher_v1"


@dataclass(frozen=True)
class MatcherEntry:
    handle: OpaqueHandle
    candidate: PeerCandidate


class PlainMatcher:
    """Query-to-top-K handle matcher using existing public manifest scores."""

    def __init__(
        self,
        entries: Sequence[MatcherEntry],
        *,
        top_k: int = 20,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        self.entries = tuple(entries)
        self.top_k = top_k

    @classmethod
    def from_records(
        cls,
        records: Sequence[PeerRecord],
        handles: Mapping[str, OpaqueHandle | OpaqueHandleRecord],
        *,
        top_k: int = 20,
    ) -> "PlainMatcher":
        entries = []
        for record in records:
            handle = handles.get(record.peer_id)
            if handle is None:
                continue
            opaque = (
                OpaqueHandle(handle.handle)
                if isinstance(handle, OpaqueHandleRecord)
                else handle
            )
            entries.append(
                MatcherEntry(
                    handle=opaque,
                    candidate=PeerCandidate(
                        _manifest_with_handle(record.manifest, opaque),
                        _observation_with_handle(record.observation, opaque),
                    ),
                )
            )
        return cls(entries, top_k=top_k)

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        if request.mode != PLAIN_MATCHER_V1:
            raise ValueError(f"unsupported matcher mode: {request.mode!r}")

        query = request.intent.query_text()
        limit = self.top_k
        if request.max_records is not None:
            limit = min(limit, request.max_records)

        # Oblivious selection: score every entry (no data-dependent skip/sort),
        # then pick top-K via a uniform-access primitive (por.oblivious). The
        # selection access pattern no longer depends on which entry matched. The
        # residual count leak (returning <K real candidates) is closed later by
        # cover handles; hardware constant-time + ORAM are the in-TEE port.
        scores = [score_manifest(entry.candidate.manifest, query) for entry in self.entries]
        selected = oblivious_top_k(scores, limit) if limit > 0 else []
        candidates = tuple(
            self.entries[i].candidate for i in selected if i != DUMMY_INDEX
        )
        return DiscoveryResult(
            candidates=candidates,
            mode=PLAIN_MATCHER_V1,
            snapshot_size=len(self.entries),
            exact_query_sent=True,
            private_query_used=False,
            generated_at=datetime.now(timezone.utc).isoformat(),
            note=(
                "oblivious top-K selection (uniform access pattern); output-count "
                "hiding via cover handles + hardware-CT/ORAM still ahead"
            ),
        )


@dataclass(frozen=True)
class MailboxEntry:
    record: OpaqueHandleRecord
    routing_kem_pk_hex: str
    peer_address: dict[str, object]


class PlainMailbox:
    """Mailbox-side handle resolver.

    This object is the only plain P0 component that knows how an opaque handle
    maps to a reachability record and routing key.
    """

    def __init__(self, entries: Sequence[MailboxEntry] = ()) -> None:
        self._entries = {entry.record.handle: entry for entry in entries}

    def add(
        self,
        *,
        record: OpaqueHandleRecord,
        routing_kem_pk_hex: str,
        peer_address: Mapping[str, object],
    ) -> None:
        if peer_address.get("peer_id") != record.handle:
            raise ValueError("mailbox peer_address record must be issued to the handle")
        bytes.fromhex(routing_kem_pk_hex)
        self._entries[record.handle] = MailboxEntry(
            record=record,
            routing_kem_pk_hex=routing_kem_pk_hex,
            peer_address=dict(peer_address),
        )

    def resolve_handle(self, handle: str) -> HandleResolution | None:
        entry = self._entries.get(handle)
        if entry is None:
            return None
        return HandleResolution(
            handle=handle,
            routing_kem_pk_hex=entry.routing_kem_pk_hex,
            peer_address=dict(entry.peer_address),
        )

    def routing_kem_pk_hex(self, handle: str) -> str | None:
        entry = self.resolve_handle(handle)
        if entry is None:
            return None
        return entry.routing_kem_pk_hex

    def to_json(self) -> str:
        data = {
            "version": "por.plain_mailbox.v1",
            "handles": sorted(self._entries),
        }
        return json.dumps(data, sort_keys=True, indent=2)


class PlainMailboxDelivery:
    """Plain mailbox transport for the committed wire shape.

    This is not the hardened oblivious mailbox. It sends sealed Outfox bytes
    from a mailbox-owned UDP socket to a reachability relay and yields sealed
    return datagrams back to the client code for decryption.
    """

    def __init__(
        self,
        mailbox: PlainMailbox,
        *,
        mailbox_sock: socket.socket,
        peer_address_config: PeerAddressConfig | None = None,
        trusted_reachability_relays: Sequence[TrustedReachabilityRelayConfig] = (),
        dev_allow_untrusted_reachability_relays: bool = False,
    ) -> None:
        self.mailbox = mailbox
        self.mailbox_sock = mailbox_sock
        self.peer_address_config = peer_address_config or PeerAddressConfig(enabled=True)
        self.trusted_reachability_relays = tuple(trusted_reachability_relays)
        self.dev_allow_untrusted_reachability_relays = dev_allow_untrusted_reachability_relays

    def relay_path_for_handle(self, handle: str) -> tuple[str, ...]:
        dial_target = self._dial_target(handle)
        if dial_target.route_kind != ROUTE_RELAY or not dial_target.relay_id:
            raise ValueError("mailbox delivery requires a reachability relay route")
        return (dial_target.relay_id,)

    def deliver_to_handle(
        self,
        handle: str,
        datagram: bytes,
        *,
        timeout: float,
    ) -> Iterator[bytes]:
        dial_target = self._dial_target(handle)
        self.mailbox_sock.settimeout(0.5)
        self.mailbox_sock.sendto(datagram, (dial_target.host, dial_target.port))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _addr = self.mailbox_sock.recvfrom(65535)
            except socket.timeout:
                continue
            yield data

    def _dial_target(self, handle: str) -> DialTarget:
        resolution = self.mailbox.resolve_handle(handle)
        if resolution is None:
            raise ValueError("handle_unresolved")
        record = peer_address_record_from_dict(dict(resolution.peer_address))
        plan = build_dial_plan(
            record,
            allow_direct=self.peer_address_config.allow_direct,
            prefer_direct=self.peer_address_config.prefer_direct,
        )
        dial_target = resolve_dial_target(
            plan,
            self.trusted_reachability_relays,
            dev_allow_untrusted_reachability_relays=self.dev_allow_untrusted_reachability_relays,
        )
        if dial_target is None:
            raise ValueError("mailbox_no_trusted_dial_target")
        return dial_target


class PlainEnclavePlaneDiscoveryProvider:
    """DiscoveryProvider facade linking plain matcher and plain mailbox."""

    def __init__(
        self,
        matcher: PlainMatcher,
        mailbox: PlainMailbox,
        delivery: PlainMailboxDelivery | None = None,
    ) -> None:
        self.matcher = matcher
        self.mailbox = mailbox
        self.delivery = delivery

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        return self.matcher.discover(request)

    @property
    def mailbox_delivery_enabled(self) -> bool:
        return self.delivery is not None

    def resolve_handle(self, handle: str) -> HandleResolution | None:
        return self.mailbox.resolve_handle(handle)

    def routing_kem_pk_hex(self, handle: str) -> str | None:
        return self.mailbox.routing_kem_pk_hex(handle)

    def relay_path_for_handle(self, handle: str) -> tuple[str, ...]:
        if self.delivery is None:
            raise ValueError("mailbox_delivery_disabled")
        return self.delivery.relay_path_for_handle(handle)

    def deliver_to_handle(
        self,
        handle: str,
        datagram: bytes,
        *,
        timeout: float,
    ) -> Iterator[bytes]:
        if self.delivery is None:
            raise ValueError("mailbox_delivery_disabled")
        return self.delivery.deliver_to_handle(handle, datagram, timeout=timeout)


def _manifest_with_handle(manifest: MemoryManifest, handle: OpaqueHandle) -> MemoryManifest:
    return replace(manifest, peer_id=handle.token)


def _observation_with_handle(observation, handle: OpaqueHandle):
    if observation is None:
        return None
    return replace(observation, peer_id=handle.token)
