"""Tests for client matcher selection (Item 6).

These pin the explicit fail-closed selection order and the concrete non-TEE
rules. The recurring scenario is "the pinned TEE matcher is offline" — the client
must degrade through the order deterministically and never silently route through
an unattested matcher.
"""

from __future__ import annotations

import pytest
from dataclasses import replace
from nacl.signing import SigningKey

from tenet.mixnet.control.descriptors import MatcherCapabilityDescriptor
from tenet.mixnet.control.match_result import MatchCandidateDescriptor, MatchResultDescriptor
from tenet.mixnet.control.policy import TrustPolicy
from tenet.mixnet.control.records import sign_control_record
from tenet.mixnet.control.service import MixnetControlService
from tenet.experts.matcher_resolver import (
    AuthorityPinnedMatcher,
    MatcherPolicy,
    MatcherResolver,
)

OPAQUE_HANDLE = "h" + "0123456789abcde"
POOL = "monet.expert~tenet"
COMMITMENT = "qc-soup"


def _service():
    sk = SigningKey.generate()
    svc = MixnetControlService(network_id="net", verify_keys={"root": sk.verify_key.encode().hex()})
    return svc, sk


def _put(svc, sk, unsigned, *, now=None, source="local", key_id="root"):
    svc.put_signed(
        sign_control_record(unsigned, signing_key_hex=sk.encode().hex(), key_id=key_id),
        now=now,
        source=source,
    )


def _tee_cap(matcher_id):
    return MatcherCapabilityDescriptor(
        matcher_id=matcher_id, pools=(POOL,), trust_tier="tee",
        result_signing_key="ff" * 32, matcher_handle=OPAQUE_HANDLE,
        attestation_ref="attestation/n/r",
    )


def _non_tee_cap(matcher_id="m-non", **overrides):
    base = dict(
        matcher_id=matcher_id, pools=(POOL,), trust_tier="non_tee_signed",
        result_signing_key="dd" * 32, query_endpoint_ref="matcher/non/endpoint",
        code_identity="sha256-code", dataset_commitment="sha256-data",
    )
    base.update(overrides)
    return MatcherCapabilityDescriptor(**base)


def _cached_result(matcher_id="m-cache"):
    return MatchResultDescriptor(
        query_commitment=COMMITMENT, pool_name=POOL, matcher_id=matcher_id,
        candidates=(MatchCandidateDescriptor(handle=OPAQUE_HANDLE, manifest_digest="d"),),
        result_nonce="n",
    )


def _policy(*, allow_non_tee=False):
    tiers = frozenset({"tee", "authority_pinned"}) | ({"non_tee_signed"} if allow_non_tee else frozenset())
    return MatcherPolicy(
        allow_non_tee_signed_fallback=allow_non_tee,
        trust_policy=TrustPolicy(allowed_trust_tiers=tiers, allow_non_tee_signed=allow_non_tee),
    )


# --------------------------------------------------------------------------- #
# the seven required scenarios
# --------------------------------------------------------------------------- #


def test_tee_offline_cached_tee_result_succeeds():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_match_result(_cached_result(), seq=1))
    resolver = MatcherResolver(_policy())
    sel = resolver.select(
        control_service=svc, pool=POOL, query_commitment=COMMITMENT,
        pinned=AuthorityPinnedMatcher("pinned-tee", online=False),
    )
    assert sel.ok
    assert sel.matcher_source == "cached_tee_result"
    assert sel.matcher_trust_tier == "tee"
    assert sel.degraded_trust is False


def test_tee_offline_alternate_tee_matcher_succeeds():
    svc, sk = _service()
    # Pin both to the same issue time so expiry is equal and the matcher_id
    # tiebreak puts a-primary first (so the unreachable path is exercised).
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee_cap("m-tee-a-primary"), seq=1, now=1000.0), now=1000.0)
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee_cap("m-tee-b-alt"), seq=1, now=1000.0), now=1000.0)
    resolver = MatcherResolver(_policy())
    # primary unreachable, alternate reachable
    reachable = lambda cand: cand.matcher_id == "m-tee-b-alt"
    sel = resolver.select(
        control_service=svc, pool=POOL, query_commitment=COMMITMENT,
        pinned=AuthorityPinnedMatcher("pinned-tee", online=False), reachable=reachable,
        now=1000.0,
    )
    assert sel.ok
    assert sel.matcher_source == "tee_capability"
    assert sel.matcher_id == "m-tee-b-alt"
    assert sel.degraded_trust is False
    assert any(r.reason == "tee_unreachable" for r in sel.rejected_matchers)


def test_tee_offline_non_tee_disabled_fails_closed():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_non_tee_cap(), seq=1))
    resolver = MatcherResolver(_policy(allow_non_tee=False))
    sel = resolver.select(
        control_service=svc, pool=POOL, query_commitment=COMMITMENT,
        pinned=AuthorityPinnedMatcher("pinned-tee", online=False),
    )
    assert sel.ok is False
    assert sel.matcher_source is None
    assert "non_tee_fallback_disabled" in (sel.fallback_reason or "")
    assert any(r.reason == "non_tee_fallback_disabled" for r in sel.rejected_matchers)


def test_tee_offline_non_tee_enabled_succeeds_degraded():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_non_tee_cap(), seq=1))
    resolver = MatcherResolver(_policy(allow_non_tee=True))
    sel = resolver.select(
        control_service=svc, pool=POOL, query_commitment=COMMITMENT,
        pinned=AuthorityPinnedMatcher("pinned-tee", online=False),
    )
    assert sel.ok
    assert sel.matcher_source == "non_tee_signed"
    assert sel.matcher_trust_tier == "non_tee_signed"
    assert sel.degraded_trust is True
    md = sel.response_metadata()
    assert md["degraded_trust"] is True
    assert md["matcher_id"] == "m-non"


def test_non_tee_missing_dataset_commitment_rejected():
    svc, sk = _service()
    cap = _non_tee_cap()
    _put(svc, sk, svc.make_unsigned_matcher_capability(cap, seq=1))
    # strip dataset_commitment from the indexed descriptor (defense-in-depth path)
    svc._matcher_capabilities[cap.matcher_id] = replace(cap, dataset_commitment=None)
    resolver = MatcherResolver(_policy(allow_non_tee=True))
    sel = resolver.select(control_service=svc, pool=POOL, query_commitment=COMMITMENT)
    assert sel.ok is False
    assert any(r.reason == "non_tee_missing_dataset_commitment" for r in sel.rejected_matchers)


def test_forged_matcher_capability_rejected_at_ingress():
    """A capability signed by a non-authorized (client) key never enters the
    service, so the resolver can never select it."""
    sk_client = SigningKey.generate()
    sk_root = SigningKey.generate()
    policy = TrustPolicy(
        verify_keys={
            "client": sk_client.verify_key.encode().hex(),
            "root": sk_root.verify_key.encode().hex(),
        },
        key_authorities={"client": "client", "root": "root"},
    )
    svc = MixnetControlService(network_id="net", trust_policy=policy)
    cap = _tee_cap("m-forged")
    from tenet.mixnet.control.records import ControlRecordError
    with pytest.raises(ControlRecordError, match="requires authority"):
        svc.put_signed(
            sign_control_record(
                svc.make_unsigned_matcher_capability(cap, seq=1),
                signing_key_hex=sk_client.encode().hex(),
                key_id="client",
            )
        )
    assert svc.matcher_capabilities(pool=POOL) == ()


def test_stale_tee_capability_rejected():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_tee_cap("m-tee"), seq=1, ttl_seconds=100, now=1000.0), now=1000.0)
    resolver = MatcherResolver(_policy())
    sel = resolver.select(control_service=svc, pool=POOL, query_commitment=COMMITMENT, now=2000.0)
    assert sel.ok is False
    assert any(r.reason == "stale_or_absent" for r in sel.rejected_matchers)


# --------------------------------------------------------------------------- #
# concrete non-TEE rule matrix
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mutation,expected_reason",
    [
        (dict(result_signing_key=""), "non_tee_missing_result_signing_key"),
        (dict(code_identity=None), "non_tee_missing_code_identity"),
        (dict(dataset_commitment=None), "non_tee_missing_dataset_commitment"),
        (dict(pools=("other.expert~tenet",)), "non_tee_pool_scope_mismatch"),
    ],
)
def test_non_tee_rule_matrix_rejects(mutation, expected_reason):
    svc, sk = _service()
    cap = _non_tee_cap()
    _put(svc, sk, svc.make_unsigned_matcher_capability(cap, seq=1))
    svc._matcher_capabilities[cap.matcher_id] = replace(cap, **mutation)
    resolver = MatcherResolver(_policy(allow_non_tee=True))
    sel = resolver.select(control_service=svc, pool=POOL, query_commitment=COMMITMENT)
    assert sel.ok is False
    assert any(r.reason == expected_reason for r in sel.rejected_matchers), [
        r.reason for r in sel.rejected_matchers
    ]


def test_non_tee_disabled_rejects_even_with_valid_capability():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_non_tee_cap(), seq=1))
    sel = MatcherResolver(_policy(allow_non_tee=False)).select(
        control_service=svc, pool=POOL, query_commitment=COMMITMENT
    )
    assert sel.ok is False
    assert any(r.reason == "non_tee_fallback_disabled" for r in sel.rejected_matchers)


def test_non_tee_enabled_accepts_and_marks_degraded():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_matcher_capability(_non_tee_cap(), seq=1))
    sel = MatcherResolver(_policy(allow_non_tee=True)).select(
        control_service=svc, pool=POOL, query_commitment=COMMITMENT
    )
    assert sel.ok and sel.degraded_trust is True
    assert sel.response_metadata()["matcher_trust_tier"] == "non_tee_signed"


# --------------------------------------------------------------------------- #
# happy path: pinned TEE online wins over everything below it
# --------------------------------------------------------------------------- #


def test_authority_pinned_used_when_online_and_no_cached_or_capability():
    svc, _sk = _service()
    sel = MatcherResolver(_policy()).select(
        control_service=svc, pool=POOL, query_commitment=COMMITMENT,
        pinned=AuthorityPinnedMatcher("pinned-tee", online=True),
    )
    assert sel.ok
    assert sel.matcher_source == "authority_pinned"
    assert sel.matcher_id == "pinned-tee"
