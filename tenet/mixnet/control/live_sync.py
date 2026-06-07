"""Client/runtime helpers for live mixnet control-record sync."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Iterable, Sequence

from tenet.config import CAPABILITY_CONTROL_DHT, ClusterConfig
from tenet.mixnet.control.records import ControlRecordError, SignedControlRecord
from tenet.mixnet.control.service import MixnetControlService
from tenet.mixnet.control.sync_state import ControlSyncState
from tenet.mixnet.control.wire import (
    ControlWireMessage,
    MSG_SYNC,
    MSG_SYNC_RESPONSE,
    decode_control_message,
    encode_control_message,
)

SYNC_SOURCE = "sync"


@dataclass(frozen=True)
class SyncOutcome:
    stored: int
    rejected: int
    reasons: tuple[str, ...] = ()


def ingest_sync_records(
    service: MixnetControlService,
    raw_records: Iterable[object],
    *,
    now: float | None = None,
    source: str = SYNC_SOURCE,
) -> SyncOutcome:
    """Validate and ingest raw records from a sync peer.

    Every record goes through ``put_signed``, so signature/TTL/network/seq/policy
    are enforced exactly as for any other ingress — a forged or stale-seq record
    from a sync peer is rejected here, not trusted because it "came from sync".
    Records are tagged with provenance ``source`` (default "sync").
    """

    stored = 0
    rejected = 0
    reasons: list[str] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            rejected += 1
            reasons.append("not_an_object")
            continue
        try:
            service.put_signed(SignedControlRecord.from_dict(raw), now=now, source=source)
            stored += 1
        except (ControlRecordError, ValueError, TypeError) as exc:
            rejected += 1
            reasons.append(type(exc).__name__)
    return SyncOutcome(stored=stored, rejected=rejected, reasons=tuple(reasons))


def dht_discovered_control_contacts(
    service: MixnetControlService | None,
    *,
    limit: int = 20,
) -> tuple[tuple[str, tuple[str, int]], ...]:
    """Control-wire contacts discovered via the attached Kademlia overlay.

    These are peers learned from the DHT routing table (not static config), so a
    client can sync control state from peers it was never explicitly told about.
    """

    overlay = getattr(service, "_kademlia_overlay", None) if service is not None else None
    if overlay is None:
        return tuple()
    fn = getattr(overlay, "control_wire_contacts", None)
    if not callable(fn):
        return tuple()
    try:
        return tuple(fn(limit=limit))
    except Exception:
        return tuple()

CONTROL_SYNC_PREFIXES: tuple[str, ...] = (
    "trust/",
    "mixnode/",
    "pool/",
    "client/",
    "name/",
    "match/",
    "expert/",
    "topic/",
    "review/",
)


def sync_control_from_cluster(
    service: MixnetControlService | None,
    cluster: ClusterConfig,
    *,
    node_ids: Sequence[str] = (),
    prefixes: Sequence[str] = CONTROL_SYNC_PREFIXES,
    timeout: float = 0.25,
    limit: int = 100,
    state: ControlSyncState | None = None,
    refresh_interval: float = 0.0,
    include_dht_discovered: bool = True,
) -> int:
    """Best-effort live sync from known + DHT-discovered control nodes.

    This does not create network truth from static config: static config only
    names initial mixnet contacts. Every returned record still passes through
    ``put_signed`` (signature/expiry/network/seq/policy) via
    :func:`ingest_sync_records`, tagged with provenance ``source="sync"``.

    When a :class:`ControlSyncState` is supplied, peers in backoff are skipped,
    failures extend their backoff, and per-prefix refresh intervals are honoured.
    """

    if service is None:
        return 0
    now = time.time()
    # Honour per-prefix refresh intervals when state is tracked.
    active_prefixes = list(prefixes)
    if state is not None and refresh_interval > 0:
        active_prefixes = [p for p in prefixes if state.due(p, refresh_interval, now)]
        if not active_prefixes:
            return 0

    targets = list(_target_addrs(cluster, node_ids=node_ids))
    if include_dht_discovered:
        targets.extend(dht_discovered_control_contacts(service))
    # De-dup and apply peer backoff.
    seen: set = set()
    usable: list[tuple[str, tuple[str, int]]] = []
    for node_id, addr in targets:
        if addr in seen:
            continue
        seen.add(addr)
        if state is not None and not state.peer_available(node_id, now):
            continue
        usable.append((node_id, addr))
    if not usable:
        return 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(min(timeout, 0.2))
    stored = 0
    contributed: set = set()
    addr_to_peer = {addr: node_id for node_id, addr in usable}
    deadline = time.time() + max(0.0, timeout)
    try:
        for node_id, addr in usable:
            for prefix in active_prefixes:
                if time.time() >= deadline:
                    break
                cursor = state.cursor(prefix) if state is not None else ""
                message = ControlWireMessage(
                    MSG_SYNC,
                    {"prefix": str(prefix), "cursor": cursor, "limit": int(limit)},
                )
                try:
                    sock.sendto(encode_control_message(message), addr)
                except OSError:
                    if state is not None:
                        state.record_peer_failure(node_id, now)
                    continue
        while time.time() < deadline:
            try:
                data, src_addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            try:
                message = decode_control_message(data)
            except (ValueError, UnicodeDecodeError):
                continue
            if message.kind != MSG_SYNC_RESPONSE:
                continue
            records = message.body.get("records") or ()
            if not isinstance(records, list):
                continue
            outcome = ingest_sync_records(service, records, source=SYNC_SOURCE)
            stored += outcome.stored
            peer = addr_to_peer.get(src_addr)
            if peer is not None:
                contributed.add(peer)
            next_cursor = message.body.get("next_cursor")
            if state is not None and isinstance(next_cursor, str) and next_cursor:
                prefix = str(message.body.get("prefix", ""))
                if prefix:
                    state.set_cursor(prefix, next_cursor)
    finally:
        sock.close()

    if state is not None:
        for node_id, _addr in usable:
            if node_id in contributed:
                state.record_peer_success(node_id)
            else:
                state.record_peer_failure(node_id, now)
        for prefix in active_prefixes:
            state.mark_refreshed(prefix, now)
        state.save()
    return stored


def run_anti_entropy_loop(
    service: MixnetControlService | None,
    cluster: ClusterConfig,
    *,
    state: ControlSyncState,
    interval: float,
    stop_event,
    prefixes: Sequence[str] = CONTROL_SYNC_PREFIXES,
    timeout: float = 0.25,
) -> None:
    """Daemon-mode anti-entropy loop: periodically sync until ``stop_event``.

    Intended to run in a background thread. Each cycle is a bounded
    :func:`sync_control_from_cluster` with backoff + cursor state; failures never
    escape the loop.
    """

    while not stop_event.is_set():
        try:
            sync_control_from_cluster(
                service, cluster, prefixes=prefixes, state=state,
                refresh_interval=interval, timeout=timeout,
            )
        except Exception:
            pass
        stop_event.wait(max(0.01, interval))


def _target_addrs(
    cluster: ClusterConfig,
    *,
    node_ids: Sequence[str],
) -> tuple[tuple[str, tuple[str, int]], ...]:
    selected = set(str(node_id) for node_id in node_ids if node_id)
    targets = []
    for node in cluster.nodes.values():
        if selected and node.node_id not in selected:
            continue
        if selected or node.has_capability(CAPABILITY_CONTROL_DHT):
            targets.append((node.node_id, (node.host, int(node.port))))
    return tuple(sorted(targets, key=lambda item: item[0]))
