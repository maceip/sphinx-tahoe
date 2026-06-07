"""Acceptance test: matcher outage fallback (Item 8).

Scenario 1 — primary pinned TEE matcher unavailable, but a fresh signed cached
TEE match result exists for the SOUP pool and Alice has an opaque handle with a
reachability route. Bob asks SOUP. The client uses the cached result and routes,
no public expertise route appears, and the outcome reports cached_match_used.

Scenario 2 — primary pinned TEE matcher unavailable, no cached TEE result, but a
non-TEE matcher capability exists. With non-TEE fallback disabled the client
fails closed; with it enabled the client routes with degraded_trust=True.
"""

from __future__ import annotations

from nacl.signing import SigningKey

from tenet.mixnet.control.descriptors import HandleAddressRecord, MatcherCapabilityDescriptor
from tenet.mixnet.control.match_result import (
    MatchCandidateDescriptor,
    MatchResultDescriptor,
    QueryCommitmentPolicy,
)
from tenet.mixnet.control.policy import TrustPolicy
from tenet.mixnet.control.records import sign_control_record
from tenet.mixnet.control.resolvers import resolve_handle_routes
from tenet.mixnet.control.service import MixnetControlService
from tenet.experts.matcher_resolver import AuthorityPinnedMatcher, MatcherPolicy, MatcherResolver

ALICE_HANDLE = "h" + "a1ce" + "0" * 11  # 'h' + 15 chars = 16 ASCII bytes
SOUP = "soup.expert~tenet"
NET = "net"


def _service():
    sk = SigningKey.generate()
    svc = MixnetControlService(network_id=NET, verify_keys={"root": sk.verify_key.encode().hex()})
    return svc, sk


def _put(svc, sk, unsigned):
    svc.put_signed(sign_control_record(unsigned, signing_key_hex=sk.encode().hex(), key_id="root"))


def _matcher_policy(*, allow_non_tee=False):
    tiers = frozenset({"tee", "authority_pinned"}) | ({"non_tee_signed"} if allow_non_tee else frozenset())
    return MatcherPolicy(
        allow_non_tee_signed_fallback=allow_non_tee,
        trust_policy=TrustPolicy(allowed_trust_tiers=tiers, allow_non_tee_signed=allow_non_tee),
    )


def _publish_alice_route(svc, sk):
    import time

    issued = time.time()
    record = HandleAddressRecord(
        handle=ALICE_HANDLE, route_candidates=("assist/relay1",), assist_refs=("assist/relay1",),
        issued_at=issued, expires_at=issued + 3600, signer="root",
    )
    _put(svc, sk, svc.make_unsigned_handle_address(record, seq=1))


def test_scenario1_cached_tee_result_used_and_routes():
    svc, sk = _service()
    commitment_policy = QueryCommitmentPolicy(network_id=NET, epoch_salt="epoch-7", dataset_commitment="soup-dataset")
    commitment = commitment_policy.derive(pool=SOUP, prompt="best soup recipe?")

    # Fresh signed cached TEE match result for SOUP, pointing at Alice's handle.
    result = MatchResultDescriptor(
        query_commitment=commitment, pool_name=SOUP, matcher_id="nitro-tee",
        candidates=(MatchCandidateDescriptor(handle=ALICE_HANDLE, manifest_digest="soup-manifest"),),
        result_nonce="r1", attestation_ref="attestation/nitro/r1",
    )
    _put(svc, sk, svc.make_unsigned_match_result(result, seq=1))
    _publish_alice_route(svc, sk)

    # Primary pinned TEE matcher is offline.
    resolver = MatcherResolver(_matcher_policy())
    sel = resolver.select(
        control_service=svc, pool=SOUP, query_commitment=commitment,
        pinned=AuthorityPinnedMatcher("nitro-pinned", online=False),
    )

    cached_match_used = sel.ok and sel.matcher_source == "cached_tee_result"
    assert cached_match_used is True
    assert sel.matcher_trust_tier == "tee"
    assert sel.degraded_trust is False

    # The selected result routes to Alice's opaque handle via her reachability
    # route — and the route is opaque (no public expertise->endpoint mapping).
    chosen = sel.selected.result.candidates[0].handle
    assert chosen == ALICE_HANDLE
    routes = resolve_handle_routes(svc, ALICE_HANDLE, TrustPolicy())
    assert routes.best() is not None
    assert routes.best().record.route_candidates == ("assist/relay1",)
    # No public expertise route appears: the route candidates are opaque assist
    # refs, never the SOUP pool name or an endpoint.
    for ref in routes.best().record.route_candidates:
        assert SOUP not in ref
        assert "://" not in ref


def test_scenario2_no_cached_non_tee_disabled_fails_closed_enabled_degrades():
    svc, sk = _service()
    commitment_policy = QueryCommitmentPolicy(network_id=NET, epoch_salt="epoch-7", dataset_commitment="soup-dataset")
    commitment = commitment_policy.derive(pool=SOUP, prompt="best soup recipe?")

    # No cached TEE result. A non-TEE matcher capability exists for SOUP.
    non_tee = MatcherCapabilityDescriptor(
        matcher_id="non-tee-soup", pools=(SOUP,), trust_tier="non_tee_signed",
        result_signing_key="dd" * 32, query_endpoint_ref="matcher/soup/endpoint",
        code_identity="sha256-code", dataset_commitment="soup-dataset",
    )
    _put(svc, sk, svc.make_unsigned_matcher_capability(non_tee, seq=1))

    pinned_offline = AuthorityPinnedMatcher("nitro-pinned", online=False)

    # Policy disabled -> fail closed.
    disabled = MatcherResolver(_matcher_policy(allow_non_tee=False)).select(
        control_service=svc, pool=SOUP, query_commitment=commitment, pinned=pinned_offline,
    )
    assert disabled.ok is False
    assert disabled.matcher_source is None
    assert any(r.reason == "non_tee_fallback_disabled" for r in disabled.rejected_matchers)

    # Policy enabled -> route with degraded_trust=True.
    enabled = MatcherResolver(_matcher_policy(allow_non_tee=True)).select(
        control_service=svc, pool=SOUP, query_commitment=commitment, pinned=pinned_offline,
    )
    assert enabled.ok is True
    assert enabled.matcher_source == "non_tee_signed"
    assert enabled.degraded_trust is True
    assert enabled.response_metadata()["degraded_trust"] is True
