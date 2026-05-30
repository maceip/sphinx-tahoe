"""Freehold-inspired UDP/QUIC peer address control plane for P-OR.

This module is intentionally detached from Outfox packet processing. It models
the transport-control primitive P-OR needs later: peers register with an inline
relay/assist, prove the relay can observe their UDP endpoint, and publish a
short-lived peer address record. The record says which relay address to dial
for this peer, and may include a direct UDP address if the peer allows that.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Sequence


PEER_ADDRESS_RECORD_V1 = "por.peer_address_record.v1"

TRANSPORT_QUIC_DATAGRAM = "quic_datagram"
TRANSPORT_WEBTRANSPORT = "webtransport"
TRANSPORT_H3_WEBSOCKET = "h3_websocket"

HEARTBEAT_INTERVAL_SECONDS = 90
REGISTRATION_TTL_SECONDS = 270
DNS_TTL_SECONDS = 810
COOKIE_BUCKET_SECONDS = 30
COOKIE_SIZE = 16

ROUTE_RELAY = "relay"
ROUTE_DIRECT = "direct"


@dataclass(frozen=True)
class UdpEndpoint:
    host: str
    port: int

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("endpoint host is required")
        if not 0 < int(self.port) <= 65535:
            raise ValueError("endpoint port must be 1..65535")

    def as_tuple(self) -> tuple[str, int]:
        return self.host, int(self.port)


@dataclass(frozen=True)
class RelayCandidate:
    relay_id: str
    endpoint: UdpEndpoint
    transport: str = TRANSPORT_QUIC_DATAGRAM
    inline_required: bool = True


@dataclass(frozen=True)
class AddressExposurePolicy:
    expose_direct_endpoint: bool = False
    stable_relay_only: bool = True


@dataclass(frozen=True)
class AddressChallenge:
    peer_id: str
    relay_id: str
    observed_endpoint: UdpEndpoint
    cookie: bytes
    issued_at: float
    expires_at: float


@dataclass(frozen=True)
class PeerAddressRecord:
    version: str
    peer_id: str
    relay_candidates: tuple[RelayCandidate, ...]
    observed_udp_endpoints: tuple[UdpEndpoint, ...]
    nat_hints: tuple[str, ...]
    supported_transports: tuple[str, ...]
    issued_at: float
    expires_at: float
    address_policy: AddressExposurePolicy
    signature: str

    def is_expired(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) >= self.expires_at

    def to_public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["observed_udp_endpoints"] = [
            endpoint for endpoint in data["observed_udp_endpoints"]
        ]
        return data


@dataclass(frozen=True)
class DialRoute:
    kind: str
    transport: str
    relay_id: str | None = None
    endpoint: UdpEndpoint | None = None
    inline_required: bool = True


@dataclass(frozen=True)
class DialPlan:
    peer_id: str
    primary: DialRoute | None
    fallbacks: tuple[DialRoute, ...]
    record_expires_at: float
    warnings: tuple[str, ...] = ()

    @property
    def contactable(self) -> bool:
        return self.primary is not None


@dataclass
class _Registration:
    peer_id: str
    observed_endpoint: UdpEndpoint
    supported_transports: tuple[str, ...]
    address_policy: AddressExposurePolicy
    nat_hints: tuple[str, ...]
    issued_at: float
    expires_at: float


class PeerAddressRelay:
    """Short-TTL relay/introducer registry.

    The challenge cookie is HMAC-bound to the peer id and observed UDP endpoint,
    following the Freehold idea of proving the requester controls the visible
    source tuple before publishing a peer address record.
    """

    def __init__(
        self,
        relay_id: str,
        relay_endpoint: UdpEndpoint,
        secret: bytes,
        *,
        ttl_seconds: int = REGISTRATION_TTL_SECONDS,
        heartbeat_interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        if not relay_id:
            raise ValueError("relay_id is required")
        if len(secret) < 16:
            raise ValueError("secret must be at least 16 bytes")
        self.relay_id = relay_id
        self.relay_endpoint = relay_endpoint
        self.secret = secret
        self.ttl_seconds = ttl_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self._registrations: dict[str, _Registration] = {}

    def request_registration(
        self,
        *,
        peer_id: str,
        observed_endpoint: UdpEndpoint,
        now: float | None = None,
    ) -> AddressChallenge:
        now = time.time() if now is None else now
        cookie = self._cookie(peer_id, observed_endpoint, self._bucket(now))
        return AddressChallenge(
            peer_id=peer_id,
            relay_id=self.relay_id,
            observed_endpoint=observed_endpoint,
            cookie=cookie,
            issued_at=now,
            expires_at=now + COOKIE_BUCKET_SECONDS,
        )

    def confirm_registration(
        self,
        challenge: AddressChallenge,
        *,
        supported_transports: Sequence[str] = (TRANSPORT_QUIC_DATAGRAM,),
        address_policy: AddressExposurePolicy | None = None,
        nat_hints: Sequence[str] = (),
        now: float | None = None,
    ) -> PeerAddressRecord:
        now = time.time() if now is None else now
        self._verify_challenge(challenge, now)
        address_policy = address_policy or AddressExposurePolicy()
        transports = tuple(dict.fromkeys(supported_transports))
        if not transports:
            raise ValueError("at least one supported transport is required")

        registration = _Registration(
            peer_id=challenge.peer_id,
            observed_endpoint=challenge.observed_endpoint,
            supported_transports=transports,
            address_policy=address_policy,
            nat_hints=tuple(nat_hints),
            issued_at=now,
            expires_at=now + self.ttl_seconds,
        )
        self._registrations[challenge.peer_id] = registration
        return self.address_record(challenge.peer_id, now=now)

    def heartbeat(
        self,
        peer_id: str,
        *,
        observed_endpoint: UdpEndpoint | None = None,
        now: float | None = None,
    ) -> PeerAddressRecord | None:
        now = time.time() if now is None else now
        registration = self._registrations.get(peer_id)
        if registration is None or registration.expires_at <= now:
            self._registrations.pop(peer_id, None)
            return None
        if observed_endpoint is not None:
            registration.observed_endpoint = observed_endpoint
        registration.expires_at = now + self.ttl_seconds
        return self.address_record(peer_id, now=now)

    def address_record(self, peer_id: str, *, now: float | None = None) -> PeerAddressRecord | None:
        now = time.time() if now is None else now
        registration = self._registrations.get(peer_id)
        if registration is None or registration.expires_at <= now:
            self._registrations.pop(peer_id, None)
            return None

        direct = (
            (registration.observed_endpoint,)
            if registration.address_policy.expose_direct_endpoint
            else ()
        )
        record = PeerAddressRecord(
            version=PEER_ADDRESS_RECORD_V1,
            peer_id=registration.peer_id,
            relay_candidates=(
                RelayCandidate(
                    relay_id=self.relay_id,
                    endpoint=self.relay_endpoint,
                    transport=registration.supported_transports[0],
                    inline_required=True,
                ),
            ),
            observed_udp_endpoints=direct,
            nat_hints=registration.nat_hints,
            supported_transports=registration.supported_transports,
            issued_at=registration.issued_at,
            expires_at=registration.expires_at,
            address_policy=registration.address_policy,
            signature="",
        )
        return record.__class__(
            **{**record.__dict__, "signature": self._record_signature(record)}
        )

    def purge_expired(self, *, now: float | None = None) -> int:
        now = time.time() if now is None else now
        expired = [
            peer_id
            for peer_id, registration in self._registrations.items()
            if registration.expires_at <= now
        ]
        for peer_id in expired:
            del self._registrations[peer_id]
        return len(expired)

    def _verify_challenge(self, challenge: AddressChallenge, now: float) -> None:
        if challenge.relay_id != self.relay_id:
            raise ValueError("challenge relay_id does not match this relay")
        if challenge.expires_at < now:
            raise ValueError("challenge expired")
        valid = (
            self._cookie(challenge.peer_id, challenge.observed_endpoint, self._bucket(now)),
            self._cookie(challenge.peer_id, challenge.observed_endpoint, self._bucket(now) - 1),
        )
        if not any(hmac.compare_digest(challenge.cookie, expected) for expected in valid):
            raise ValueError("invalid peer address challenge cookie")

    def _bucket(self, now: float) -> int:
        return int(now // COOKIE_BUCKET_SECONDS)

    def _cookie(self, peer_id: str, endpoint: UdpEndpoint, bucket: int) -> bytes:
        msg = f"{peer_id}|{endpoint.host}|{endpoint.port}|{bucket}".encode("utf-8")
        return hmac.new(self.secret, msg, sha256).digest()[:COOKIE_SIZE]

    def _record_signature(self, record: PeerAddressRecord) -> str:
        relay_bits = ",".join(
            f"{candidate.relay_id}@{candidate.endpoint.host}:{candidate.endpoint.port}:{candidate.transport}"
            for candidate in record.relay_candidates
        )
        direct_bits = ",".join(
            f"{endpoint.host}:{endpoint.port}" for endpoint in record.observed_udp_endpoints
        )
        msg = "|".join(
            (
                record.version,
                record.peer_id,
                relay_bits,
                direct_bits,
                ",".join(record.supported_transports),
                str(int(record.expires_at)),
            )
        ).encode("utf-8")
        return hmac.new(self.secret, msg, sha256).hexdigest()


def build_dial_plan(
    record: PeerAddressRecord,
    *,
    allow_direct: bool = False,
    prefer_direct: bool = False,
    now: float | None = None,
) -> DialPlan:
    """Build the relay-first list of addresses to try for a peer."""

    now = time.time() if now is None else now
    warnings: list[str] = []
    if record.is_expired(now):
        return DialPlan(
            peer_id=record.peer_id,
            primary=None,
            fallbacks=(),
            record_expires_at=record.expires_at,
            warnings=("peer address record expired",),
        )

    relay_routes = tuple(
        DialRoute(
            kind=ROUTE_RELAY,
            relay_id=candidate.relay_id,
            endpoint=candidate.endpoint,
            transport=candidate.transport,
            inline_required=candidate.inline_required,
        )
        for candidate in record.relay_candidates
    )

    direct_allowed = allow_direct and record.address_policy.expose_direct_endpoint
    direct_routes = tuple(
        DialRoute(
            kind=ROUTE_DIRECT,
            endpoint=endpoint,
            transport=record.supported_transports[0],
            inline_required=False,
        )
        for endpoint in record.observed_udp_endpoints
    ) if direct_allowed else ()

    if allow_direct and record.observed_udp_endpoints and not direct_allowed:
        warnings.append("direct endpoints suppressed by peer privacy policy")

    ordered = (
        direct_routes + relay_routes
        if prefer_direct and direct_routes
        else relay_routes + direct_routes
    )
    if not ordered:
        warnings.append("no relay or direct endpoint in peer address record")

    return DialPlan(
        peer_id=record.peer_id,
        primary=ordered[0] if ordered else None,
        fallbacks=ordered[1:],
        record_expires_at=record.expires_at,
        warnings=tuple(warnings),
    )
