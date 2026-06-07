"""Trust-aware resolvers over the control service.

Product code must not hand-read raw signed records and make its own trust
decisions inline — that is where trust drift creeps in. Instead it asks a
resolver, which returns a :class:`ResolutionResult`: the accepted candidates
ranked best-first, *and* a structured list of everything it rejected and why.

The resolvers are the single place that:
  * filters by trust tier / authority,
  * drops stale, revoked, or expired records,
  * attributes provenance (local cache vs DHT vs sync),
  * ranks candidates deterministically,
  * records a machine-readable rejection reason for every candidate it drops.

A caller that wants to know "why did I fall back?" reads ``result.rejected``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from tenet.mixnet.control.descriptors import (
    MatcherCapabilityDescriptor,
    ReachabilityAssistDescriptor,
    HandleAddressRecord,
    MixnetRoutingDescriptor,
)
from tenet.mixnet.control.match_result import MatchResultDescriptor
from tenet.mixnet.control.policy import TrustPolicy
from tenet.mixnet.control.service import MixnetControlService

T = TypeVar("T")

ResolutionSource = Literal["local", "dht", "sync", "bootstrap", "unknown"]

# Trust-tier ranking for matcher selection: lower sorts first (better).
_TIER_RANK = {"tee": 0, "authority_pinned": 1, "non_tee_signed": 2}


@dataclass(frozen=True)
class RejectedCandidate:
    """A candidate the resolver dropped, with a machine-readable reason."""

    key: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ResolutionResult(Generic[T]):
    """Accepted candidates (ranked best-first) plus structured rejections."""

    candidates: tuple[T, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()

    def best(self) -> T | None:
        return self.candidates[0] if self.candidates else None

    def __bool__(self) -> bool:
        return bool(self.candidates)

    def __iter__(self):
        return iter(self.candidates)

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        return tuple(r.reason for r in self.rejected)


@dataclass(frozen=True)
class MatcherCandidate:
    matcher_id: str
    descriptor: MatcherCapabilityDescriptor
    trust_tier: str
    source: ResolutionSource
    record_key: str
    expires_at: float
    degraded_trust: bool = False


@dataclass(frozen=True)
class MatchResultCandidate:
    result: MatchResultDescriptor
    source: ResolutionSource
    record_key: str
    issued_at: float
    expires_at: float


@dataclass(frozen=True)
class ReachabilityCandidate:
    assist_id: str
    descriptor: ReachabilityAssistDescriptor
    source: ResolutionSource
    record_key: str
    expires_at: float


@dataclass(frozen=True)
class HandleRouteCandidate:
    handle: str
    record: HandleAddressRecord
    source: ResolutionSource
    record_key: str
    expires_at: float


@dataclass(frozen=True)
class MixPathCandidate:
    node_id: str
    descriptor: MixnetRoutingDescriptor
    source: ResolutionSource
    record_key: str
    expires_at: float


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _source(service: MixnetControlService, key: str) -> ResolutionSource:
    return service.record_source(key) or "unknown"  # type: ignore[return-value]


def _fresh_signed(service: MixnetControlService, key: str, *, now: float | None):
    """Return the signed record for ``key`` if live, else (None, reason).

    ``service.get`` already enforces revocation + expiry (and may pull from the
    DHT), so a None here means revoked, expired, or simply absent.
    """

    if service.is_revoked(key):
        return None, "revoked"
    signed = service.get(key, now=now)
    if signed is None:
        return None, "stale_or_absent"
    return signed, ""


def _tier_allowed(trust_tier: str, policy: TrustPolicy) -> tuple[bool, str]:
    if trust_tier in policy.allowed_trust_tiers:
        return True, ""
    if trust_tier == "non_tee_signed":
        if policy.allow_non_tee_signed:
            return True, ""
        return False, "non_tee_disabled"
    return False, "trust_tier_not_allowed"


# --------------------------------------------------------------------------- #
# resolvers
# --------------------------------------------------------------------------- #


def resolve_matcher_candidates(
    service: MixnetControlService,
    pool: str,
    policy: TrustPolicy,
    *,
    now: float | None = None,
) -> ResolutionResult[MatcherCandidate]:
    """Rank usable matcher capabilities for ``pool`` under ``policy``.

    Ranking: trust tier (tee < authority_pinned < non_tee_signed), then later
    expiry first (fresher capability), then matcher_id for determinism.
    """

    accepted: list[MatcherCandidate] = []
    rejected: list[RejectedCandidate] = []
    # Iterate the raw index (not the freshness-filtered accessor) so the resolver
    # is the single freshness authority and can report stale/revoked rejections.
    for cap in sorted(service._matcher_capabilities.values(), key=lambda c: c.matcher_id):
        if pool not in cap.pools:
            continue
        signed, reason = _fresh_signed(service, cap.key, now=now)
        if signed is None:
            rejected.append(RejectedCandidate(cap.key, reason, cap.matcher_id))
            continue
        ok, tier_reason = _tier_allowed(cap.trust_tier, policy)
        if not ok:
            rejected.append(RejectedCandidate(cap.key, tier_reason, cap.trust_tier))
            continue
        if not cap.result_signing_key:
            rejected.append(RejectedCandidate(cap.key, "missing_result_signing_key", cap.matcher_id))
            continue
        accepted.append(
            MatcherCandidate(
                matcher_id=cap.matcher_id,
                descriptor=cap,
                trust_tier=cap.trust_tier,
                source=_source(service, cap.key),
                record_key=cap.key,
                expires_at=signed.record.expires_at,
                degraded_trust=cap.trust_tier == "non_tee_signed",
            )
        )
    accepted.sort(
        key=lambda c: (_TIER_RANK.get(c.trust_tier, 99), -c.expires_at, c.matcher_id)
    )
    return ResolutionResult(tuple(accepted), tuple(rejected))


def resolve_cached_match_results(
    service: MixnetControlService,
    pool: str,
    query_commitment: str,
    policy: TrustPolicy,
    *,
    now: float | None = None,
) -> ResolutionResult[MatchResultCandidate]:
    """Cached signed match results for an exact (pool, query_commitment).

    A result whose candidates are all cover traffic is rejected (cover-only is
    not a routable answer). Ranking: most recently issued first.
    """

    accepted: list[MatchResultCandidate] = []
    rejected: list[RejectedCandidate] = []
    raw = [
        r
        for r in service._match_results.values()
        if r.pool_name == pool and r.query_commitment == query_commitment
    ]
    for result in sorted(raw, key=lambda r: r.matcher_id):
        signed, reason = _fresh_signed(service, result.key, now=now)
        if signed is None:
            rejected.append(RejectedCandidate(result.key, reason, result.matcher_id))
            continue
        if all(candidate.cover for candidate in result.candidates):
            rejected.append(RejectedCandidate(result.key, "cover_only", result.matcher_id))
            continue
        accepted.append(
            MatchResultCandidate(
                result=result,
                source=_source(service, result.key),
                record_key=result.key,
                issued_at=signed.record.issued_at,
                expires_at=signed.record.expires_at,
            )
        )
    accepted.sort(key=lambda c: (-c.issued_at, c.result.matcher_id))
    return ResolutionResult(tuple(accepted), tuple(rejected))


def resolve_reachability_assists(
    service: MixnetControlService,
    policy: TrustPolicy,
    *,
    region_hint: str | None = None,
    now: float | None = None,
) -> ResolutionResult[ReachabilityCandidate]:
    """Live reachability assists, optionally preferring a region hint.

    Ranking: assists whose policy mentions ``region_hint`` first, then later
    expiry first, then assist_id.
    """

    accepted: list[ReachabilityCandidate] = []
    rejected: list[RejectedCandidate] = []
    for assist in sorted(service._reachability_assists.values(), key=lambda a: a.assist_id):
        signed, reason = _fresh_signed(service, assist.key, now=now)
        if signed is None:
            rejected.append(RejectedCandidate(assist.key, reason, assist.assist_id))
            continue
        accepted.append(
            ReachabilityCandidate(
                assist_id=assist.assist_id,
                descriptor=assist,
                source=_source(service, assist.key),
                record_key=assist.key,
                expires_at=signed.record.expires_at,
            )
        )

    def _region_match(c: ReachabilityCandidate) -> int:
        if not region_hint:
            return 0
        haystack = " ".join((c.descriptor.policy, *c.descriptor.opaque_refs)).lower()
        return 0 if region_hint.lower() in haystack else 1

    accepted.sort(key=lambda c: (_region_match(c), -c.expires_at, c.assist_id))
    return ResolutionResult(tuple(accepted), tuple(rejected))


def resolve_handle_routes(
    service: MixnetControlService,
    handle: str,
    policy: TrustPolicy,
    *,
    now: float | None = None,
) -> ResolutionResult[HandleRouteCandidate]:
    """Resolve the signed handle-address record for ``handle`` into routes.

    A handle binds to at most one address record. It is rejected if it is
    stale/revoked or carries no usable route (no candidates, no assists, and
    direct dial not allowed).
    """

    key = f"handle/{handle}/address"
    record = service._handle_addresses.get(handle)
    if record is None:
        return ResolutionResult((), (RejectedCandidate(key, "no_handle_address", handle),))
    signed, reason = _fresh_signed(service, key, now=now)
    if signed is None:
        return ResolutionResult((), (RejectedCandidate(key, reason, handle),))
    if not record.route_candidates and not record.assist_refs and not record.direct_allowed:
        return ResolutionResult((), (RejectedCandidate(key, "no_route", handle),))
    candidate = HandleRouteCandidate(
        handle=handle,
        record=record,
        source=_source(service, key),
        record_key=key,
        expires_at=signed.record.expires_at,
    )
    return ResolutionResult((candidate,), ())


def resolve_mix_path_candidates(
    service: MixnetControlService,
    policy: TrustPolicy,
    *,
    now: float | None = None,
) -> ResolutionResult[MixPathCandidate]:
    """Live mixnet routing descriptors usable as mix-path hops."""

    accepted: list[MixPathCandidate] = []
    rejected: list[RejectedCandidate] = []
    for mr in sorted(service._mixnet_routings.values(), key=lambda m: m.node_id):
        signed, reason = _fresh_signed(service, mr.key, now=now)
        if signed is None:
            rejected.append(RejectedCandidate(mr.key, reason, mr.node_id))
            continue
        accepted.append(
            MixPathCandidate(
                node_id=mr.node_id,
                descriptor=mr,
                source=_source(service, mr.key),
                record_key=mr.key,
                expires_at=signed.record.expires_at,
            )
        )
    accepted.sort(key=lambda c: c.node_id)
    return ResolutionResult(tuple(accepted), tuple(rejected))
