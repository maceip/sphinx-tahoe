"""End-to-end: paid, challenge-bound, honesty-checked query session."""

from __future__ import annotations

import random

import pytest

from tenet.arc_session import answer_paid_query, close_paid_query, open_paid_query
from tenet.blind_rsa import IssuerKey
from tenet.mixnet.control.pools import PoolDescriptor
from tenet.rate_token import (
    IssuanceCap,
    NullifierLedger,
    TokenSpendError,
    begin_token,
    complete_token,
    issue_blind_sig,
)
from tenet.reputation import AuditPolicy, ReputationLedger

POOL = "soup.expert~tenet"
NET = "net"
SALT = "epoch-2026-06"


@pytest.fixture(scope="module")
def issuer():
    return IssuerKey.generate(bits=2048)


def _pool(issuer):
    return PoolDescriptor(
        name=POOL, topic_tags=("soup",),
        arc_issuer_key_pem=issuer.public.to_pem().decode("utf-8"),
        pay_to="ALGO_ADDR", token_epoch="2026-06",
    )


def _token(issuer):
    cap = IssuanceCap()
    req = begin_token(issuer.public)
    bs = issue_blind_sig(issuer, req.blinded_msg, identity="alice", epoch="2026-06", cap=cap)
    return complete_token(issuer.public, req, bs)


def test_full_paid_query_soft_tier(issuer):
    pool = _pool(issuer)
    ledger = NullifierLedger()
    rep = ReputationLedger(flag_threshold=1)

    paid = open_paid_query(
        pool_descriptor=pool, token=_token(issuer), ledger=ledger,
        network_id=NET, pool_name=POOL, prompt="best soup?", epoch_salt=SALT,
    )
    answer = "Make a good stock first."
    receipt = answer_paid_query(challenge_dict=paid.challenge_dict, answer=answer)

    verdict = close_paid_query(
        paid_query=paid, answer=answer, receipt=receipt, expert_id="chef",
        reputation_ledger=rep, audit_policy=AuditPolicy(audit_rate=1.0), rng=random.Random(1),
    )
    assert verdict.ok and verdict.degraded_trust is True and verdict.hard_proof is False
    assert ledger.is_spent(paid.token_nullifier)
    assert not rep.is_flagged("chef")  # honest answer passed audit


def test_paid_query_requires_a_valid_token(issuer):
    pool = _pool(issuer)
    ledger = NullifierLedger()
    other = IssuerKey.generate(bits=2048)
    bad_token = _token(other)  # minted by the wrong issuer
    with pytest.raises(TokenSpendError, match="does not verify"):
        open_paid_query(
            pool_descriptor=pool, token=bad_token, ledger=ledger,
            network_id=NET, pool_name=POOL, prompt="x", epoch_salt=SALT,
        )


def test_token_double_spend_blocked_across_queries(issuer):
    pool = _pool(issuer)
    ledger = NullifierLedger()
    token = _token(issuer)
    open_paid_query(pool_descriptor=pool, token=token, ledger=ledger,
                    network_id=NET, pool_name=POOL, prompt="a", epoch_salt=SALT)
    with pytest.raises(TokenSpendError, match="double-spend"):
        open_paid_query(pool_descriptor=pool, token=token, ledger=ledger,
                        network_id=NET, pool_name=POOL, prompt="b", epoch_salt=SALT)


def test_lied_answer_fails_verification_and_flags(issuer):
    pool = _pool(issuer)
    ledger = NullifierLedger()
    rep = ReputationLedger(flag_threshold=1)
    paid = open_paid_query(pool_descriptor=pool, token=_token(issuer), ledger=ledger,
                           network_id=NET, pool_name=POOL, prompt="q", epoch_salt=SALT)
    receipt = answer_paid_query(challenge_dict=paid.challenge_dict, answer="real answer")
    # asker actually received a tampered answer
    verdict = close_paid_query(
        paid_query=paid, answer="TAMPERED answer", receipt=receipt, expert_id="liar",
        reputation_ledger=rep, audit_policy=AuditPolicy(audit_rate=1.0),
    )
    assert not verdict.ok
    assert rep.is_flagged("liar")


def test_attested_tier_gives_hard_proof(issuer):
    import hashlib

    pool = _pool(issuer)
    ledger = NullifierLedger()
    rep = ReputationLedger()
    secret = b"cloud-tee-key"
    tee_sign = lambda p: hashlib.sha256(secret + p.encode()).hexdigest()
    tee_verify = lambda p, s: s == hashlib.sha256(secret + p.encode()).hexdigest()

    paid = open_paid_query(pool_descriptor=pool, token=_token(issuer), ledger=ledger,
                           network_id=NET, pool_name=POOL, prompt="q", epoch_salt=SALT)
    answer = "attested answer"
    receipt = answer_paid_query(challenge_dict=paid.challenge_dict, answer=answer, attested=True, tee_sign=tee_sign)
    verdict = close_paid_query(paid_query=paid, answer=answer, receipt=receipt, expert_id="tee-expert",
                               reputation_ledger=rep, tee_verify=tee_verify)
    assert verdict.ok and verdict.hard_proof is True and verdict.degraded_trust is False


def test_different_dataset_changes_commitment(issuer):
    pool = _pool(issuer)
    ledger = NullifierLedger()
    p1 = open_paid_query(pool_descriptor=pool, token=_token(issuer), ledger=ledger,
                         network_id=NET, pool_name=POOL, prompt="q", epoch_salt=SALT, dataset_commitment="ds1")
    p2 = open_paid_query(pool_descriptor=pool, token=_token(issuer), ledger=ledger,
                         network_id=NET, pool_name=POOL, prompt="q", epoch_salt=SALT, dataset_commitment="ds2")
    assert p1.query_commitment != p2.query_commitment
