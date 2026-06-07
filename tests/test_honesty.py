"""Tests for Phase-1 execution honesty (asker challenge + two-tier receipts)."""

from __future__ import annotations

import hashlib

from tenet.honesty import (
    AskerChallenge,
    HonestyTier,
    make_attested_receipt,
    make_soft_receipt,
    verify_receipt,
)

ANSWER = "Monet broke light into discrete strokes of unmixed colour."
QC = "qc-soup-abc"


def _tee_keypair():
    secret = b"tee-demo-secret"
    sign = lambda payload: hashlib.sha256(secret + payload.encode()).hexdigest()
    verify = lambda payload, sig: sig == hashlib.sha256(secret + payload.encode()).hexdigest()
    return sign, verify


def test_soft_receipt_verifies_but_is_degraded():
    ch = AskerChallenge.issue(QC)
    receipt = make_soft_receipt(ch, ANSWER)
    v = verify_receipt(receipt, ch, ANSWER)
    assert v.ok
    assert v.tier == HonestyTier.SOFT.value
    assert v.hard_proof is False
    assert v.degraded_trust is True


def test_attested_receipt_is_hard_proof():
    sign, verify = _tee_keypair()
    ch = AskerChallenge.issue(QC)
    receipt = make_attested_receipt(ch, ANSWER, sign)
    v = verify_receipt(receipt, ch, ANSWER, tee_verify=verify)
    assert v.ok and v.hard_proof is True and v.degraded_trust is False


def test_wrong_answer_rejected():
    ch = AskerChallenge.issue(QC)
    receipt = make_soft_receipt(ch, ANSWER)
    v = verify_receipt(receipt, ch, "a different, faked answer")
    assert not v.ok and v.reason == "answer_hash_mismatch"


def test_replayed_to_a_different_query_rejected():
    # a receipt minted for one challenge can't pass verification for another
    ch1 = AskerChallenge.issue(QC)
    ch2 = AskerChallenge.issue("qc-other")
    receipt = make_soft_receipt(ch1, ANSWER)
    v = verify_receipt(receipt, ch2, ANSWER)
    assert not v.ok and v.reason == "challenge_mismatch"


def test_forged_attestation_rejected():
    _sign, verify = _tee_keypair()
    ch = AskerChallenge.issue(QC)
    # attacker claims attested tier but signs with the wrong key
    bad_sign = lambda payload: "deadbeef" * 8
    receipt = make_attested_receipt(ch, ANSWER, bad_sign)
    v = verify_receipt(receipt, ch, ANSWER, tee_verify=verify)
    assert not v.ok and v.reason == "bad_attestation"


def test_attested_tier_without_verifier_fails_closed():
    sign, _verify = _tee_keypair()
    ch = AskerChallenge.issue(QC)
    receipt = make_attested_receipt(ch, ANSWER, sign)
    # asker has no TEE verifier configured -> cannot grant hard proof
    v = verify_receipt(receipt, ch, ANSWER, tee_verify=None)
    assert not v.ok and v.reason == "missing_attestation"


def test_nonce_is_unforceable_fresh_each_time():
    a = AskerChallenge.issue(QC)
    b = AskerChallenge.issue(QC)
    assert a.nonce != b.nonce
