"""Match-result gossip fallback tests (Item 8).

When the live matcher is unavailable, a fresh signed cached result for the exact
query can carry the client. These tests pin the commitment binding (network,
dataset, epoch, prompt, expertise, pool) and every reason a cached result must be
refused: stale, wrong prompt, wrong dataset, forged, cover-only, and a result
whose handle has no reachability.
"""

from __future__ import annotations

import pytest
from nacl.signing import SigningKey

from tenet.mixnet.control.match_result import (
    MatchCandidateDescriptor,
    MatchResultDescriptor,
    QueryCommitmentPolicy,
    derive_query_commitment,
)
from tenet.mixnet.control.policy import TrustPolicy
from tenet.mixnet.control.records import ControlRecordError, sign_control_record
from tenet.mixnet.control.resolvers import resolve_cached_match_results, resolve_handle_routes
from tenet.mixnet.control.service import MixnetControlService

OPAQUE_HANDLE = "h" + "0123456789abcde"
POOL = "monet.expert~tenet"
NET = "net"


def _service(**kw):
    sk = SigningKey.generate()
    svc = MixnetControlService(network_id=NET, verify_keys={"root": sk.verify_key.encode().hex()}, **kw)
    return svc, sk


def _put(svc, sk, unsigned, *, now=None, key_id="root"):
    svc.put_signed(sign_control_record(unsigned, signing_key_hex=sk.encode().hex(), key_id=key_id), now=now)


def _result(commitment, *, matcher_id="m1", cover=False, handle=OPAQUE_HANDLE):
    return MatchResultDescriptor(
        query_commitment=commitment, pool_name=POOL, matcher_id=matcher_id,
        candidates=(MatchCandidateDescriptor(handle=handle, manifest_digest="d", cover=cover),),
        result_nonce="n-" + matcher_id,
    )


# --------------------------------------------------------------------------- #
# commitment binding
# --------------------------------------------------------------------------- #


def test_derive_query_commitment_is_deterministic():
    a = derive_query_commitment(network_id=NET, pool=POOL, prompt="soup?", expertise="cooking", dataset_commitment="ds1", epoch_salt="e1")
    b = derive_query_commitment(network_id=NET, pool=POOL, prompt="soup?", expertise="cooking", dataset_commitment="ds1", epoch_salt="e1")
    assert a == b


@pytest.mark.parametrize("change", ["network_id", "pool", "prompt", "expertise", "dataset_commitment", "epoch_salt"])
def test_derive_query_commitment_changes_with_every_input(change):
    base = dict(network_id=NET, pool=POOL, prompt="soup?", expertise="cooking", dataset_commitment="ds1", epoch_salt="e1")
    other = dict(base)
    other[change] = {
        "network_id": "net2", "pool": "ramen.expert~tenet", "prompt": "salad?",
        "expertise": "baking", "dataset_commitment": "ds2", "epoch_salt": "e2",
    }[change]
    assert derive_query_commitment(**base) != derive_query_commitment(**other)


def test_query_commitment_policy_threads_dataset_and_epoch():
    policy = QueryCommitmentPolicy(network_id=NET, epoch_salt="e1", dataset_commitment="ds1")
    direct = derive_query_commitment(network_id=NET, pool=POOL, prompt="soup?", dataset_commitment="ds1", epoch_salt="e1")
    assert policy.derive(pool=POOL, prompt="soup?") == direct


# --------------------------------------------------------------------------- #
# fallback acceptance + rejections
# --------------------------------------------------------------------------- #


def _commit(prompt="soup?", dataset="ds1", epoch="e1"):
    return derive_query_commitment(network_id=NET, pool=POOL, prompt=prompt, dataset_commitment=dataset, epoch_salt=epoch)


def test_live_matcher_offline_fresh_signed_result_routes():
    svc, sk = _service()
    commitment = _commit()
    _put(svc, sk, svc.make_unsigned_match_result(_result(commitment), seq=1))
    result = resolve_cached_match_results(svc, POOL, commitment, TrustPolicy())
    assert result.best() is not None
    assert result.best().result.candidates[0].handle == OPAQUE_HANDLE


def test_stale_result_rejected():
    svc, sk = _service()
    commitment = _commit()
    _put(svc, sk, svc.make_unsigned_match_result(_result(commitment), seq=1, ttl_seconds=100, now=1000.0), now=1000.0)
    result = resolve_cached_match_results(svc, POOL, commitment, TrustPolicy(), now=2000.0)
    assert result.candidates == ()
    assert "stale_or_absent" in result.rejection_reasons


def test_wrong_prompt_rejected():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_match_result(_result(_commit(prompt="soup?")), seq=1))
    # query for a different prompt -> different commitment -> no match
    result = resolve_cached_match_results(svc, POOL, _commit(prompt="salad?"), TrustPolicy())
    assert result.candidates == ()


def test_wrong_dataset_rejected():
    svc, sk = _service()
    _put(svc, sk, svc.make_unsigned_match_result(_result(_commit(dataset="ds1")), seq=1))
    result = resolve_cached_match_results(svc, POOL, _commit(dataset="ds2"), TrustPolicy())
    assert result.candidates == ()


def test_cover_only_result_rejected():
    svc, sk = _service()
    commitment = _commit()
    _put(svc, sk, svc.make_unsigned_match_result(_result(commitment, cover=True), seq=1))
    result = resolve_cached_match_results(svc, POOL, commitment, TrustPolicy())
    assert result.candidates == ()
    assert "cover_only" in result.rejection_reasons


def test_forged_result_rejected_at_ingest():
    """A match result signed by a client-authority key never enters the service."""
    sk_client = SigningKey.generate()
    sk_root = SigningKey.generate()
    policy = TrustPolicy(
        verify_keys={"client": sk_client.verify_key.encode().hex(), "root": sk_root.verify_key.encode().hex()},
        key_authorities={"client": "client", "root": "root"},
    )
    svc = MixnetControlService(network_id=NET, trust_policy=policy)
    commitment = _commit()
    with pytest.raises(ControlRecordError, match="requires authority"):
        svc.put_signed(
            sign_control_record(
                svc.make_unsigned_match_result(_result(commitment), seq=1),
                signing_key_hex=sk_client.encode().hex(),
                key_id="client",
            )
        )
    assert resolve_cached_match_results(svc, POOL, commitment, policy).candidates == ()


def test_unresolved_handle_is_not_a_success():
    """A cached result is selectable, but if its handle has no reachability the
    route resolution must fail clearly rather than count as a success."""
    svc, sk = _service()
    commitment = _commit()
    _put(svc, sk, svc.make_unsigned_match_result(_result(commitment), seq=1))
    cached = resolve_cached_match_results(svc, POOL, commitment, TrustPolicy())
    assert cached.best() is not None
    handle = cached.best().result.candidates[0].handle
    # No handle-address record was published for this handle.
    routes = resolve_handle_routes(svc, handle, TrustPolicy())
    assert routes.candidates == ()
    assert "no_handle_address" in routes.rejection_reasons
