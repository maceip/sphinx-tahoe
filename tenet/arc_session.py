"""Paid-query session: the real wire tying token + challenge + honesty together.

This is what the asker and expert use around a query, composing the bedrock:

  asker.open_paid_query()   -> spends a rate-limit token under the pool's
                               committed issuer key (the gate), binds the query
                               commitment, and mints a fresh unforceable challenge
  expert.answer_paid_query() -> returns the answer + an execution receipt (soft,
                               or attested if it runs in a cloud TEE)
  asker.close_paid_query()  -> verifies the receipt against the challenge and
                               records the soft-tier reputation / spot-audit

Every step is real (no MAC, no stub): blind-RSA token, SQLite nullifier ledger,
nonce-bound honesty receipts, reputation ledger.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from tenet.honesty import (
    AskerChallenge,
    ExecutionReceipt,
    HonestyVerdict,
    make_attested_receipt,
    make_soft_receipt,
    verify_receipt,
)
from tenet.mixnet.control.match_result import derive_query_commitment
from tenet.rate_token import NullifierLedger, RateLimitToken, spend_token_for_pool
from tenet.reputation import AuditPolicy, ReputationLedger, record_and_maybe_audit


@dataclass(frozen=True)
class PaidQuery:
    """Asker-held state for one paid query."""

    challenge: AskerChallenge
    query_commitment: str
    token_nullifier: str

    @property
    def challenge_dict(self) -> dict[str, str]:
        return {"nonce": self.challenge.nonce, "query_commitment": self.challenge.query_commitment}


def open_paid_query(
    *,
    pool_descriptor,
    token: RateLimitToken,
    ledger: NullifierLedger,
    network_id: str,
    pool_name: str,
    prompt: str,
    epoch_salt: str,
    expertise: str | None = None,
    dataset_commitment: str | None = None,
    now: float | None = None,
) -> PaidQuery:
    """Spend the token (rate-limit gate) and open a challenge-bound query."""
    # 1. rate-limit gate: token must verify under the pool's *committed* issuer key
    nullifier = spend_token_for_pool(pool_descriptor, token, ledger, now=now)
    # 2. bind the query (network + dataset + epoch + prompt + expertise)
    commitment = derive_query_commitment(
        network_id=network_id, pool=pool_name, prompt=prompt,
        expertise=expertise, dataset_commitment=dataset_commitment, epoch_salt=epoch_salt,
    )
    # 3. fresh, unforceable challenge bound to that commitment
    challenge = AskerChallenge.issue(commitment)
    return PaidQuery(challenge=challenge, query_commitment=commitment, token_nullifier=nullifier)


def answer_paid_query(
    *,
    challenge_dict: dict[str, str],
    answer: str,
    attested: bool = False,
    tee_sign=None,
) -> ExecutionReceipt:
    """Expert side: produce the execution receipt for an answer.

    SOFT by default (laptop expert); ATTESTED if running in a cloud TEE with a
    ``tee_sign`` callable (the real aw attestation path at deploy time).
    """
    challenge = AskerChallenge(nonce=challenge_dict["nonce"], query_commitment=challenge_dict["query_commitment"])
    if attested:
        if tee_sign is None:
            raise ValueError("attested tier requires a TEE signer")
        return make_attested_receipt(challenge, answer, tee_sign)
    return make_soft_receipt(challenge, answer)


def close_paid_query(
    *,
    paid_query: PaidQuery,
    answer: str,
    receipt: ExecutionReceipt,
    expert_id: str,
    reputation_ledger: ReputationLedger,
    audit_policy: AuditPolicy | None = None,
    tee_verify=None,
    rng: random.Random | None = None,
) -> HonestyVerdict:
    """Asker side: verify the receipt and record the soft-tier reputation/audit."""
    verdict = verify_receipt(receipt, paid_query.challenge, answer, tee_verify=tee_verify)
    record_and_maybe_audit(
        expert_id=expert_id, receipt=receipt, challenge=paid_query.challenge, answer=answer,
        ledger=reputation_ledger, policy=audit_policy or AuditPolicy(), rng=rng,
        extra_quality_ok=None if verdict.ok else False,
    )
    return verdict
