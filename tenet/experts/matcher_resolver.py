"""Client-side matcher selection (Item 6).

Removes "one matcher to rule them all" as a failure mode. The client picks a
matcher by an explicit, fail-closed priority order and never silently downgrades
trust. Non-TEE matchers are usable only when an operator opts in, and even then
only when they carry the full evidence a client needs to verify their results.

The resolver is a pure decision function: it consults the control service and a
caller-supplied reachability predicate, and returns a :class:`MatcherSelection`
with the trust metadata the response must surface. Network IO (actually probing
the matcher) is the caller's job; reachability is injected so this stays testable
and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tenet.mixnet.control.policy import TrustPolicy
from tenet.mixnet.control.resolvers import (
    MatcherCandidate,
    RejectedCandidate,
    resolve_cached_match_results,
    resolve_matcher_candidates,
)

DEFAULT_FALLBACK_ORDER: tuple[str, ...] = (
    "cached_tee_result",
    "tee_capability",
    "authority_pinned",
    "non_tee_signed",
)


@dataclass(frozen=True)
class AuthorityPinnedMatcher:
    """A matcher pinned by the join pack / authority (e.g. attested enclave)."""

    matcher_id: str
    online: bool = True
    trust_tier: str = "authority_pinned"


@dataclass(frozen=True)
class MatcherPolicy:
    """Knobs controlling matcher selection."""

    allow_non_tee_signed_fallback: bool = False
    matcher_timeout_seconds: float = 8.0
    matcher_fallback_order: tuple[str, ...] = DEFAULT_FALLBACK_ORDER
    trust_policy: TrustPolicy = field(default_factory=TrustPolicy)

    @classmethod
    def from_client_config(cls, config, *, trust_policy: TrustPolicy | None = None) -> "MatcherPolicy":
        order = tuple(getattr(config, "matcher_fallback_order", DEFAULT_FALLBACK_ORDER)) or DEFAULT_FALLBACK_ORDER
        base = trust_policy or TrustPolicy()
        # The matcher policy's allow flag and the resolver trust_policy's
        # allow_non_tee_signed must agree, so non-TEE capabilities actually
        # surface from the resolver when (and only when) the operator opted in.
        allow = bool(getattr(config, "allow_non_tee_signed_fallback", False))
        resolver_policy = TrustPolicy(
            verify_keys=base.verify_keys,
            key_authorities=base.key_authorities,
            record_policy=base.record_policy,
            threshold=base.threshold,
            default_authority=base.default_authority,
            allowed_trust_tiers=frozenset({"tee", "authority_pinned"})
            | ({"non_tee_signed"} if allow else frozenset()),
            allow_non_tee_signed=allow,
            max_staleness_seconds=base.max_staleness_seconds,
        )
        return cls(
            allow_non_tee_signed_fallback=allow,
            matcher_timeout_seconds=float(getattr(config, "matcher_timeout_seconds", 8.0)),
            matcher_fallback_order=order,
            trust_policy=resolver_policy,
        )


@dataclass(frozen=True)
class MatcherSelection:
    """Outcome of matcher selection, including the metadata a response must echo."""

    ok: bool
    matcher_source: str | None = None
    matcher_id: str | None = None
    matcher_trust_tier: str | None = None
    degraded_trust: bool = False
    fallback_reason: str | None = None
    rejected_matchers: tuple[RejectedCandidate, ...] = ()
    # The underlying selected object (MatchResultCandidate / MatcherCandidate /
    # AuthorityPinnedMatcher), for the caller to act on.
    selected: object | None = None

    def response_metadata(self) -> dict[str, object]:
        return {
            "matcher_source": self.matcher_source,
            "matcher_id": self.matcher_id,
            "matcher_trust_tier": self.matcher_trust_tier,
            "degraded_trust": self.degraded_trust,
            "fallback_reason": self.fallback_reason,
            "rejected_matchers": [
                {"key": r.key, "reason": r.reason, "detail": r.detail}
                for r in self.rejected_matchers
            ],
        }


class MatcherResolver:
    """Selects a matcher by the explicit fail-closed order."""

    def __init__(self, policy: MatcherPolicy) -> None:
        self.policy = policy

    def select(
        self,
        *,
        control_service,
        pool: str,
        query_commitment: str | None = None,
        pinned: AuthorityPinnedMatcher | None = None,
        reachable: Callable[[MatcherCandidate], bool] | None = None,
        now: float | None = None,
    ) -> MatcherSelection:
        rejected: list[RejectedCandidate] = []
        reasons: list[str] = []

        for step in self.policy.matcher_fallback_order:
            if step == "cached_tee_result":
                sel = self._step_cached_tee_result(
                    control_service, pool, query_commitment, rejected, reasons, now
                )
            elif step == "tee_capability":
                sel = self._step_tee_capability(
                    control_service, pool, reachable, rejected, reasons, now
                )
            elif step == "authority_pinned":
                sel = self._step_authority_pinned(pinned, rejected, reasons)
            elif step == "non_tee_signed":
                sel = self._step_non_tee_signed(control_service, pool, rejected, reasons, now)
            else:  # pragma: no cover - config.validate guards this
                continue
            if sel is not None:
                # attach the rejections/fallback trail accumulated so far
                return MatcherSelection(
                    ok=True,
                    matcher_source=sel.matcher_source,
                    matcher_id=sel.matcher_id,
                    matcher_trust_tier=sel.matcher_trust_tier,
                    degraded_trust=sel.degraded_trust,
                    fallback_reason="; ".join(reasons) or None,
                    rejected_matchers=tuple(rejected),
                    selected=sel.selected,
                )

        # 5. Fail closed.
        return MatcherSelection(
            ok=False,
            matcher_source=None,
            fallback_reason="; ".join(reasons) or "no_matcher_available",
            rejected_matchers=tuple(rejected),
        )

    # --- steps ------------------------------------------------------------- #

    def _step_cached_tee_result(self, control_service, pool, query_commitment, rejected, reasons, now):
        if control_service is None or not query_commitment:
            reasons.append("no_query_commitment_for_cache")
            return None
        res = resolve_cached_match_results(
            control_service, pool, query_commitment, self.policy.trust_policy, now=now
        )
        rejected.extend(res.rejected)
        best = res.best()
        if best is None:
            reasons.append("no_fresh_cached_tee_result")
            return None
        return MatcherSelection(
            ok=True,
            matcher_source="cached_tee_result",
            matcher_id=best.result.matcher_id,
            matcher_trust_tier="tee",
            degraded_trust=False,
            selected=best,
        )

    def _step_tee_capability(self, control_service, pool, reachable, rejected, reasons, now):
        if control_service is None:
            return None
        res = resolve_matcher_candidates(control_service, pool, self.policy.trust_policy, now=now)
        rejected.extend(r for r in res.rejected if r not in rejected)
        for cand in res.candidates:
            if cand.trust_tier != "tee":
                continue
            if reachable is not None and not reachable(cand):
                rejected.append(RejectedCandidate(cand.record_key, "tee_unreachable", cand.matcher_id))
                continue
            return MatcherSelection(
                ok=True,
                matcher_source="tee_capability",
                matcher_id=cand.matcher_id,
                matcher_trust_tier="tee",
                degraded_trust=False,
                selected=cand,
            )
        reasons.append("no_reachable_tee_capability")
        return None

    def _step_authority_pinned(self, pinned, rejected, reasons):
        if pinned is None:
            reasons.append("no_authority_pinned_matcher")
            return None
        if not pinned.online:
            rejected.append(
                RejectedCandidate(pinned.matcher_id, "authority_pinned_offline", pinned.matcher_id)
            )
            reasons.append("authority_pinned_offline")
            return None
        return MatcherSelection(
            ok=True,
            matcher_source="authority_pinned",
            matcher_id=pinned.matcher_id,
            matcher_trust_tier=pinned.trust_tier,
            degraded_trust=False,
            selected=pinned,
        )

    def _step_non_tee_signed(self, control_service, pool, rejected, reasons, now):
        # The concrete non-TEE rules, enforced in code (not prose). This iterates
        # the raw index rather than the generic resolver, because the generic
        # resolver silently skips out-of-pool caps and uses generic reasons — the
        # non-TEE gate must produce its own precise non_tee_* rejection reasons.
        if not self.policy.allow_non_tee_signed_fallback:
            rejected.append(RejectedCandidate("", "non_tee_fallback_disabled", pool))
            reasons.append("non_tee_fallback_disabled")
            return None
        if control_service is None:
            return None
        caps = sorted(
            (
                cap
                for cap in control_service._matcher_capabilities.values()
                if cap.trust_tier == "non_tee_signed"
            ),
            key=lambda c: c.matcher_id,
        )
        for cap in caps:
            # Must be backed by a fresh, unrevoked signed record (= a real signed
            # capability). service.get enforces revocation + expiry.
            if control_service.is_revoked(cap.key):
                rejected.append(RejectedCandidate(cap.key, "revoked", cap.matcher_id))
                continue
            signed = control_service.get(cap.key, now=now)
            if signed is None:
                rejected.append(RejectedCandidate(cap.key, "non_tee_unsigned_capability", cap.matcher_id))
                continue
            if not cap.result_signing_key:
                rejected.append(RejectedCandidate(cap.key, "non_tee_missing_result_signing_key", cap.matcher_id))
                continue
            if not cap.code_identity:
                rejected.append(RejectedCandidate(cap.key, "non_tee_missing_code_identity", cap.matcher_id))
                continue
            if not cap.dataset_commitment:
                rejected.append(RejectedCandidate(cap.key, "non_tee_missing_dataset_commitment", cap.matcher_id))
                continue
            if pool not in cap.pools:
                rejected.append(RejectedCandidate(cap.key, "non_tee_pool_scope_mismatch", cap.matcher_id))
                continue
            return MatcherSelection(
                ok=True,
                matcher_source="non_tee_signed",
                matcher_id=cap.matcher_id,
                matcher_trust_tier="non_tee_signed",
                degraded_trust=True,
                fallback_reason="non_tee_signed_matcher",
                selected=cap,
            )
        reasons.append("no_usable_non_tee_matcher")
        return None
