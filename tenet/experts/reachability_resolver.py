"""Dynamic reachability assist selection (Item 7).

Routes to a matched opaque handle using *discovered* reachability assists, not
only a statically-configured relay. A static relay is a bootstrap fallback, not
the only path — otherwise "everyone talks to one relay" becomes both a privacy
sink and a single point of failure.

Selection is fail-closed and evidence-gated:
  * a DHT-discovered route requires a signed handle-address record,
  * each assist must be a trusted, fresh, signed assist descriptor,
  * an assist with no live handle mapping is skipped and the next is tried,
  * a direct route is used only when policy allows and the record permits it.

Liveness is injected (``live_probe``) so this stays deterministic and testable;
the real probe is a REACH liveness check / bounded delivery retry in the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from tenet.mixnet.control.policy import TrustPolicy
from tenet.mixnet.control.resolvers import (
    RejectedCandidate,
    resolve_handle_routes,
    resolve_reachability_assists,
)

# live_probe(assist_id, handle) -> bool : does this assist have a live mapping
# for this handle right now?
LiveProbe = Callable[[str, str], bool]


@dataclass(frozen=True)
class ReachabilityPolicy:
    allow_direct: bool = False
    trusted_assist_ids: frozenset = frozenset()
    require_signed_handle_address: bool = True
    max_assist_attempts: int = 8
    trust_policy: TrustPolicy = field(default_factory=TrustPolicy)


@dataclass(frozen=True)
class ReachabilitySelection:
    ok: bool
    handle: str
    route_kind: str | None = None  # "direct" | "assist" | "static_relay"
    assist_id: str | None = None
    static_relay_id: str | None = None
    handle_live_state: str = "unknown"  # "live" | "no_live_mapping" | "unknown"
    fallback_reason: str | None = None
    rejected: tuple[RejectedCandidate, ...] = ()
    logs: tuple[str, ...] = ()


class RouteHealthCache:
    """Tracks per-target failures so dead assists/relays get backed off.

    A target with ``>= fail_threshold`` consecutive failures is unhealthy until a
    success resets it. Deterministic (no wall-clock): callers decide when to
    retry by clearing or by recording a success.
    """

    def __init__(self, *, fail_threshold: int = 3) -> None:
        self.fail_threshold = fail_threshold
        self._failures: dict[str, int] = {}

    def record_success(self, target: str) -> None:
        self._failures[target] = 0

    def record_failure(self, target: str) -> None:
        self._failures[target] = self._failures.get(target, 0) + 1

    def failures(self, target: str) -> int:
        return self._failures.get(target, 0)

    def is_healthy(self, target: str) -> bool:
        return self._failures.get(target, 0) < self.fail_threshold


def resolve_reachability_for_handle(
    handle: str,
    service,
    static_relays: Sequence,
    policy: ReachabilityPolicy,
    *,
    live_probe: LiveProbe | None = None,
    health: RouteHealthCache | None = None,
    now: float | None = None,
) -> ReachabilitySelection:
    rejected: list[RejectedCandidate] = []
    logs: list[str] = []
    health = health or RouteHealthCache()

    routes = resolve_handle_routes(service, handle, policy.trust_policy, now=now)
    handle_route = routes.best()
    rejected.extend(routes.rejected)

    if handle_route is None and policy.require_signed_handle_address:
        # No signed handle-address record: a DHT-discovered route cannot be used.
        # The only thing left is a static relay bootstrap fallback.
        logs.append(f"client event=handle_live_state handle={handle} state=no_signed_address")
        return _static_relay_fallback(handle, static_relays, policy, health, rejected, logs,
                                      base_reason="no_signed_handle_address")

    if handle_route is not None:
        record = handle_route.record
        # Direct route preferred when policy allows and the record permits it.
        if policy.allow_direct and record.direct_allowed:
            logs.append(f"client event=assist_selected handle={handle} route=direct source={handle_route.source}")
            logs.append(f"client event=handle_live_state handle={handle} state=direct")
            return ReachabilitySelection(
                ok=True, handle=handle, route_kind="direct",
                handle_live_state="live", rejected=tuple(rejected), logs=tuple(logs),
            )

        # Build the set of trusted, fresh, signed assists.
        live_assists = {
            c.assist_id: c
            for c in resolve_reachability_assists(service, policy.trust_policy, now=now).candidates
        }
        attempts = 0
        saw_no_live_mapping = False
        for assist_id in record.assist_refs:
            if attempts >= policy.max_assist_attempts:
                break
            attempts += 1
            if assist_id not in live_assists:
                rejected.append(RejectedCandidate(assist_id, "assist_unknown_or_stale", handle))
                logs.append(f"client event=assist_rejected assist={assist_id} reason=unknown_or_stale")
                continue
            if policy.trusted_assist_ids and assist_id not in policy.trusted_assist_ids:
                rejected.append(RejectedCandidate(assist_id, "assist_untrusted", handle))
                logs.append(f"client event=assist_rejected assist={assist_id} reason=untrusted")
                continue
            if not health.is_healthy(assist_id):
                rejected.append(RejectedCandidate(assist_id, "assist_unhealthy", handle))
                logs.append(f"client event=assist_rejected assist={assist_id} reason=unhealthy_backoff")
                continue
            live = True if live_probe is None else bool(live_probe(assist_id, handle))
            if not live:
                saw_no_live_mapping = True
                health.record_failure(assist_id)
                rejected.append(RejectedCandidate(assist_id, "assist_no_live_mapping", handle))
                logs.append(
                    f"client event=handle_live_state handle={handle} assist={assist_id} state=no_live_mapping"
                )
                continue  # retry next assist
            health.record_success(assist_id)
            logs.append(f"client event=assist_selected assist={assist_id} handle={handle} source={live_assists[assist_id].source}")
            logs.append(f"client event=handle_live_state handle={handle} assist={assist_id} state=live")
            return ReachabilitySelection(
                ok=True, handle=handle, route_kind="assist", assist_id=assist_id,
                handle_live_state="live", rejected=tuple(rejected), logs=tuple(logs),
            )

        base_reason = "all_assists_no_live_mapping" if saw_no_live_mapping else "no_usable_assist"
        return _static_relay_fallback(handle, static_relays, policy, health, rejected, logs,
                                      base_reason=base_reason,
                                      live_state="no_live_mapping" if saw_no_live_mapping else "unknown")

    # handle_route is None but signed address not required -> static fallback
    return _static_relay_fallback(handle, static_relays, policy, health, rejected, logs,
                                  base_reason="no_handle_address")


def _static_relay_fallback(handle, static_relays, policy, health, rejected, logs, *,
                           base_reason: str, live_state: str = "unknown") -> ReachabilitySelection:
    for relay in static_relays:
        relay_id = getattr(relay, "relay_id", None) or str(relay)
        if not health.is_healthy(relay_id):
            rejected.append(RejectedCandidate(relay_id, "static_relay_unhealthy", handle))
            continue
        logs.append(f"client event=assist_selected static_relay={relay_id} handle={handle} route=bootstrap_fallback")
        return ReachabilitySelection(
            ok=True, handle=handle, route_kind="static_relay", static_relay_id=relay_id,
            handle_live_state=live_state, rejected=tuple(rejected), logs=tuple(logs),
            fallback_reason=base_reason,
        )
    # Nothing worked.
    reason = f"{base_reason}; no_static_relay" if not static_relays else f"{base_reason}; all_static_relays_unhealthy"
    logs.append(f"client event=reachability_exhausted handle={handle} reason={reason}")
    return ReachabilitySelection(
        ok=False, handle=handle, route_kind=None, handle_live_state=live_state,
        fallback_reason=reason, rejected=tuple(rejected), logs=tuple(logs),
    )
