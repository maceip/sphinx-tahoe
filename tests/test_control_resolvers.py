"""Tests for the trust-aware control resolvers (Item 2).

Resolvers are the single place product code asks "what may I use, and why was
everything else rejected?" These tests pin ranking, trust-tier filtering,
staleness/revocation rejection with reasons, and source attribution.
"""

from __future__ import annotations

import time

from nacl.signing import SigningKey

from tenet.mixnet.control.descriptors import (
    MatcherCapabilityDescriptor,
    ReachabilityAssistDescriptor,
    HandleAddressRecord,
)
from tenet.mixnet.control.match_result import MatchCandidateDescriptor, MatchResultDescriptor
from tenet.mixnet.control.policy import TrustPolicy
from tenet.mixnet.control.records import sign_control_record
from tenet.mixnet.control.resolvers import (
    resolve_cached_match_results,
    resolve_handle_routes,
    resolve_matcher_candidates,
    resolve_reachability_assists,
)
from tenet.mixnet.control.service import MixnetControlService

OPAQUE_HANDLE = "h" + "0123456789abcde"
POOL = "monet.expert~tenet"


def _service():
    sk = SigningKey.generate()
    svc = MixnetControlService(network_id="net", verify_keys={"root": sk.verify_key.encode().hex()})
    return svc, sk


def _put(svc, sk, unsigned, *, now=None, source="local"):
    svc.put_signed(
        sign_control_record(unsigned, signing_key_hex=sk.encode().hex(), key_id="root"),
        now=now,
        source=source,
    )


def _tee(matcher_id="m-tee"):
    return MatcherCapabilityDescriptor(
        matcher_id=matcher_id, pools=(POOL,), trust_tier="tee",
        result_signing_key="ff" * 32, matcher_handle=OPAQUE_HANDLE,
        attestation_ref="attestation/n/r",
    )


def _authority_pinned(matcher_id="m-auth"):
    return MatcherCapabilityDescriptor(
        matcher_id=matcher_id, pools=(POOL,), trust_tier="authority_pinned",
        result_signing_key="ee" * 32, query_endpoint_ref="matcher/auth/endpoint",
    )


def _non_tee(matcher_id="m-non"):
    return MatcherCapabilityDescriptor(
        matcher_id=matcher_id, pools=(POOL,), trust_tier="non_tee_signed",
        result_signing_key="dd" * 32, query_endpoint_ref="matcher/non/endpoint",
        code_identity="sha256-code", dataset_commitment="sha256-data",
    )


def _allow_all() -> TrustPolicy:
    return TrustPolicy(
        allowed_trust_tiers=frozenset({"tee", "authority_pinned", "non_tee_signed"}),
        allow_non_tee_signed=True,
    )


# --------------------------------------------------------------------------- #
# matcher ranking + trust-tier filtering
# --------------------------------------------------------------------------- #


def test_matcher_candidates_ranked_tee_first():
    svc, sk = _service()
    # insert in deliberately reversed priority order
    _put(svc, sk, svc.make_unsigned_matcher_capability(_non_tee(), seq=1))
    _put(svc, sk, svc.make_unsigned_matcher_capability(_authority_pinned(), seq=1))
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee(), seq=1))
    result = resolve_matcher_candidates(svc, POOL, _allow_all())
    assert [c.trust_tier for c in result.candidates] == ["tee", "authority_pinned", "non_tee_signed"]
    assert result.best().trust_tier == "tee"
    assert result.best().degraded_trust is False


def test_matcher_non_tee_marked_degraded():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_non_tee(), seq=1))
    result = resolve_matcher_candidates(svc, POOL, _allow_all())
    assert result.best().degraded_trust is True


def test_matcher_non_tee_rejected_when_disabled_default_policy():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee(), seq=1))
    _put(svc, sk, svc.make_unsigned_matcher_capability(_non_tee(), seq=1))
    result = resolve_matcher_candidates(svc, POOL, TrustPolicy())  # default: tee/authority only
    assert [c.trust_tier for c in result.candidates] == ["tee"]
    reasons = {r.reason for r in result.rejected}
    assert "non_tee_disabled" in reasons


def test_matcher_trust_tier_filtering_tee_only():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee(), seq=1))
    _put(svc, sk, svc.make_unsigned_matcher_capability(_authority_pinned(), seq=1))
    policy = TrustPolicy(allowed_trust_tiers=frozenset({"tee"}), allow_non_tee_signed=False)
    result = resolve_matcher_candidates(svc, POOL, policy)
    assert [c.trust_tier for c in result.candidates] == ["tee"]
    assert any(r.reason == "trust_tier_not_allowed" for r in result.rejected)


def test_matcher_pool_scope_filtering():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee(), seq=1))
    result = resolve_matcher_candidates(svc, "other.expert~tenet", _allow_all())
    assert result.candidates == ()


# --------------------------------------------------------------------------- #
# staleness + revocation rejection reasons
# --------------------------------------------------------------------------- #


def test_matcher_stale_capability_rejected_with_reason():
    svc, sk = _service()
    # fresh at t=1000, expires at 1100
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee(), seq=1, ttl_seconds=100, now=1000.0), now=1000.0)
    result = resolve_matcher_candidates(svc, POOL, _allow_all(), now=2000.0)
    assert result.candidates == ()
    assert [r.reason for r in result.rejected] == ["stale_or_absent"]


def test_matcher_revoked_capability_rejected_with_reason():
    svc, sk = _service()
    cap = _tee()
    _put(svc, sk, svc.make_unsigned_matcher_capability(cap, seq=1))
    _put(svc, sk, svc.make_unsigned_revocation(cap.key, seq=1))
    result = resolve_matcher_candidates(svc, POOL, _allow_all())
    assert result.candidates == ()
    assert [r.reason for r in result.rejected] == ["revoked"]


def test_matcher_missing_result_signing_key_rejected():
    """Resolver defense-in-depth: even if a capability without a result signing
    key somehow lands in the index (it can't via put_signed — the descriptor
    rejects it — but a future ingress path might), the resolver drops it."""
    from dataclasses import replace

    svc, sk = _service()
    cap = _tee()
    _put(svc, sk, svc.make_unsigned_matcher_capability(cap, seq=1))  # fresh signed record exists
    # Overwrite only the indexed descriptor the resolver inspects with one whose
    # result_signing_key is empty. The signed record at cap.key stays valid.
    svc._matcher_capabilities[cap.matcher_id] = replace(cap, result_signing_key="")
    result = resolve_matcher_candidates(svc, POOL, _allow_all())
    assert result.candidates == ()
    assert [r.reason for r in result.rejected] == ["missing_result_signing_key"]


# --------------------------------------------------------------------------- #
# source attribution (DHT)
# --------------------------------------------------------------------------- #


def test_matcher_dht_sourced_attributed():
    svc, sk = _service()
    # A capability that arrived via the DHT fetch path is tagged source="dht".
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee(), seq=1), source="dht")
    result = resolve_matcher_candidates(svc, POOL, _allow_all())
    assert result.best().source == "dht"


def test_matcher_local_sourced_attributed():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee(), seq=1))
    result = resolve_matcher_candidates(svc, POOL, _allow_all())
    assert result.best().source == "local"


# --------------------------------------------------------------------------- #
# cached match results
# --------------------------------------------------------------------------- #


def _match_result(matcher_id, commitment, *, cover=False):
    return MatchResultDescriptor(
        query_commitment=commitment,
        pool_name=POOL,
        matcher_id=matcher_id,
        candidates=(MatchCandidateDescriptor(handle=OPAQUE_HANDLE, manifest_digest="d", cover=cover),),
        result_nonce="n-" + matcher_id,
    )


def test_cached_match_results_cover_only_rejected():
    svc, sk = _service()
    commitment = "qc"
    _put(svc, sk, svc.make_unsigned_match_result(_match_result("m1", commitment, cover=True), seq=1))
    result = resolve_cached_match_results(svc, POOL, commitment, _allow_all())
    assert result.candidates == ()
    assert [r.reason for r in result.rejected] == ["cover_only"]


def test_cached_match_results_ranked_by_recency():
    svc, sk = _service()
    commitment = "qc"
    _put(svc, sk, svc.make_unsigned_match_result(_match_result("m-old", commitment), seq=1, ttl_seconds=10000, now=1000.0), now=1000.0)
    _put(svc, sk, svc.make_unsigned_match_result(_match_result("m-new", commitment), seq=1, ttl_seconds=10000, now=1500.0), now=1500.0)
    result = resolve_cached_match_results(svc, POOL, commitment, _allow_all(), now=1600.0)
    assert [c.result.matcher_id for c in result.candidates] == ["m-new", "m-old"]


def test_cached_match_results_wrong_commitment_empty():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_match_result(_match_result("m1", "qc-a"), seq=1))
    result = resolve_cached_match_results(svc, POOL, "qc-b", _allow_all())
    assert result.candidates == ()


# --------------------------------------------------------------------------- #
# handle routes + reachability assists
# --------------------------------------------------------------------------- #


def test_handle_routes_missing_address():
    svc, _sk = _service()
    result = resolve_handle_routes(svc, OPAQUE_HANDLE, _allow_all())
    assert result.candidates == ()
    assert [r.reason for r in result.rejected] == ["no_handle_address"]


def test_handle_routes_resolved():
    svc, sk = _service()
    issued = time.time()
    record = HandleAddressRecord(
        handle=OPAQUE_HANDLE, route_candidates=("assist/a1",), assist_refs=("assist/a1",),
        issued_at=issued, expires_at=issued + 3600, signer="root",
    )
    _put(svc, sk, svc.make_unsigned_handle_address(record, seq=1))
    result = resolve_handle_routes(svc, OPAQUE_HANDLE, _allow_all())
    assert result.best().record.route_candidates == ("assist/a1",)


def test_reachability_region_hint_ranks_first():
    svc, sk = _service()
    a_eu = ReachabilityAssistDescriptor(assist_id="a-eu", provider_node_id="n1", policy="nat-relay-eu")
    a_us = ReachabilityAssistDescriptor(assist_id="a-us", provider_node_id="n2", policy="nat-relay-us")
    _put(svc, sk, svc.make_unsigned_reachability_assist(a_us, seq=1))
    _put(svc, sk, svc.make_unsigned_reachability_assist(a_eu, seq=1))
    result = resolve_reachability_assists(svc, _allow_all(), region_hint="eu")
    assert result.best().assist_id == "a-eu"
