"""Tests for the soft-tier reputation + spot-audit ledger."""

from __future__ import annotations

import random

from tenet.honesty import AskerChallenge, make_attested_receipt, make_soft_receipt
from tenet.reputation import (
    AuditPolicy,
    ReputationLedger,
    record_and_maybe_audit,
)

ANSWER = "an answer"
QC = "qc-1"


def test_served_and_flagging():
    led = ReputationLedger(flag_threshold=2)
    led.record_served("e1")
    led.record_served("e1")
    assert led.stats("e1").served == 2
    assert led.record_audit("e1", passed=False) is False  # 1 failure
    assert led.record_audit("e1", passed=False) is True   # 2 failures -> flagged
    assert led.is_flagged("e1")


def test_passed_audits_do_not_flag():
    led = ReputationLedger(flag_threshold=1)
    for _ in range(5):
        led.record_audit("e2", passed=True)
    assert not led.is_flagged("e2")
    assert led.stats("e2").audit_failure_rate == 0.0


def test_audit_catches_a_lied_answer():
    led = ReputationLedger(flag_threshold=1)
    ch = AskerChallenge.issue(QC)
    receipt = make_soft_receipt(ch, ANSWER)
    # always audit; the answer the asker actually received differs (expert lied)
    always = AuditPolicy(audit_rate=1.0)
    record_and_maybe_audit(
        expert_id="liar", receipt=receipt, challenge=ch, answer="a DIFFERENT answer",
        ledger=led, policy=always,
    )
    assert led.is_flagged("liar")  # binding mismatch -> failed audit -> flagged


def test_honest_soft_answer_passes_audit():
    led = ReputationLedger(flag_threshold=1)
    ch = AskerChallenge.issue(QC)
    receipt = make_soft_receipt(ch, ANSWER)
    record_and_maybe_audit(
        expert_id="honest", receipt=receipt, challenge=ch, answer=ANSWER,
        ledger=led, policy=AuditPolicy(audit_rate=1.0),
    )
    assert not led.is_flagged("honest")
    assert led.stats("honest").served == 1


def test_attested_tier_skips_audit():
    led = ReputationLedger(flag_threshold=1)
    ch = AskerChallenge.issue(QC)
    sign = lambda p: "sig"
    receipt = make_attested_receipt(ch, ANSWER, sign)
    record_and_maybe_audit(
        expert_id="tee", receipt=receipt, challenge=ch, answer=ANSWER,
        ledger=led, policy=AuditPolicy(audit_rate=1.0),
    )
    # served recorded, but no audit attempted (hard proof already)
    assert led.stats("tee").served == 1
    assert led.stats("tee").audited == 0


def test_audit_sampling_rate_is_respected():
    pol = AuditPolicy(audit_rate=0.3)
    rng = random.Random(42)
    hits = sum(pol.should_audit(rng) for _ in range(10000))
    assert 2500 < hits < 3500  # ~30%


def test_durable_across_restart(tmp_path):
    db = str(tmp_path / "rep.db")
    led = ReputationLedger(db, flag_threshold=1)
    led.record_audit("e", passed=False)
    led.close()
    led2 = ReputationLedger(db, flag_threshold=1)
    assert led2.is_flagged("e")
    led2.close()
