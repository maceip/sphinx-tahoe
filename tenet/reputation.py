"""Soft-tier execution-honesty enforcement: reputation + spot-audit ledger.

A laptop expert can't hardware-attest its frontier call, so the soft tier's trust
comes from *behaviour over time*, not a one-shot crypto proof. This ledger is the
real mechanism:

- every served answer is recorded,
- a random sample is audited (the asker's nonce-bound receipt is re-checked, and
  out-of-band quality signals can be folded in),
- an expert whose audited answers fail accumulates audit failures and gets
  **flagged** past a threshold, which the matcher/asker can use to stop routing
  to it.

Durable + concurrency-safe (SQLite). The attested tier (opt-in cloud TEE) gives a
hard proof instead and bypasses this; see ``tenet/honesty.py``.
"""

from __future__ import annotations

import random
import sqlite3
import threading
import time
from dataclasses import dataclass

from tenet.honesty import AskerChallenge, ExecutionReceipt, HonestyTier, verify_receipt


@dataclass(frozen=True)
class ReputationStats:
    expert_id: str
    served: int
    audited: int
    audit_failures: int
    flagged: bool

    @property
    def audit_failure_rate(self) -> float:
        return (self.audit_failures / self.audited) if self.audited else 0.0


class ReputationLedger:
    """Per-expert served/audited/failure counters with a flag threshold."""

    def __init__(self, path: str = ":memory:", *, flag_threshold: int = 3) -> None:
        self.flag_threshold = int(flag_threshold)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS reputation ("
            "expert_id TEXT PRIMARY KEY, served INTEGER DEFAULT 0, "
            "audited INTEGER DEFAULT 0, audit_failures INTEGER DEFAULT 0, "
            "flagged INTEGER DEFAULT 0)"
        )
        self._conn.commit()

    def _ensure(self, expert_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO reputation (expert_id) VALUES (?)", (expert_id,)
        )

    def record_served(self, expert_id: str) -> None:
        with self._lock:
            self._ensure(expert_id)
            self._conn.execute(
                "UPDATE reputation SET served = served + 1 WHERE expert_id = ?", (expert_id,)
            )
            self._conn.commit()

    def record_audit(self, expert_id: str, *, passed: bool) -> bool:
        """Record an audit outcome. Returns True if the expert is now flagged."""
        with self._lock:
            self._ensure(expert_id)
            if passed:
                self._conn.execute(
                    "UPDATE reputation SET audited = audited + 1 WHERE expert_id = ?",
                    (expert_id,),
                )
            else:
                self._conn.execute(
                    "UPDATE reputation SET audited = audited + 1, "
                    "audit_failures = audit_failures + 1 WHERE expert_id = ?",
                    (expert_id,),
                )
            row = self._conn.execute(
                "SELECT audit_failures FROM reputation WHERE expert_id = ?", (expert_id,)
            ).fetchone()
            flagged = row[0] >= self.flag_threshold
            if flagged:
                self._conn.execute(
                    "UPDATE reputation SET flagged = 1 WHERE expert_id = ?", (expert_id,)
                )
            self._conn.commit()
            return flagged

    def is_flagged(self, expert_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT flagged FROM reputation WHERE expert_id = ?", (expert_id,)
            ).fetchone()
            return bool(row and row[0])

    def stats(self, expert_id: str) -> ReputationStats:
        with self._lock:
            row = self._conn.execute(
                "SELECT served, audited, audit_failures, flagged FROM reputation "
                "WHERE expert_id = ?", (expert_id,)
            ).fetchone()
        if row is None:
            return ReputationStats(expert_id, 0, 0, 0, False)
        return ReputationStats(expert_id, row[0], row[1], row[2], bool(row[3]))

    def close(self) -> None:
        with self._lock:
            self._conn.close()


@dataclass(frozen=True)
class AuditPolicy:
    """How often soft-tier answers are spot-audited."""

    audit_rate: float = 0.1  # fraction of served answers to audit

    def should_audit(self, rng: random.Random | None = None) -> bool:
        r = rng or random
        return r.random() < self.audit_rate


def record_and_maybe_audit(
    *,
    expert_id: str,
    receipt: ExecutionReceipt,
    challenge: AskerChallenge,
    answer: str,
    ledger: ReputationLedger,
    policy: AuditPolicy,
    rng: random.Random | None = None,
    extra_quality_ok: bool | None = None,
) -> ReputationStats:
    """Soft-tier outcome: always record served; sometimes audit.

    An audit re-checks the asker's nonce-bound receipt against the answer (so a
    lied-about answer fails) and may fold in an out-of-band quality signal
    (``extra_quality_ok``). Attested-tier receipts skip this — they already carry
    a hard proof.
    """

    ledger.record_served(expert_id)
    if receipt.tier == HonestyTier.ATTESTED.value:
        return ledger.stats(expert_id)
    if policy.should_audit(rng):
        verdict = verify_receipt(receipt, challenge, answer)
        passed = verdict.ok and (extra_quality_ok is not False)
        ledger.record_audit(expert_id, passed=passed)
    return ledger.stats(expert_id)
