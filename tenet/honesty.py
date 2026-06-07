"""Phase-1 execution honesty: asker challenge + two-tier receipts.

The asker is the verifier. It issues a fresh, *unforceable* challenge bound to
its query, and verifies the expert's receipt offline. Two tiers:

- SOFT (any laptop expert): no hardware attestation exists on consumer machines,
  so the receipt is structural only; trust comes from reputation + spot-audit.
- ATTESTED (opt-in cloud-TEE expert): the receipt carries a TEE signature the
  asker verifies — a hard provenance proof. Per-expert, no single point of
  failure. (Same two-tier shape as the matcher: tee / non_tee_signed.)

This is the Phase-1 stand-in; real TEE attestation reuses the attested-workload
`aw` path. See the design memory for why interactive MPC-TLS was rejected.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class HonestyTier(str, Enum):
    SOFT = "soft"
    ATTESTED = "attested"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AskerChallenge:
    """A fresh nonce the expert must bind into its frontier call. The asker picks
    it, so the expert cannot precompute, replay, or force a colluding pairing."""

    nonce: str
    query_commitment: str

    @classmethod
    def issue(cls, query_commitment: str) -> "AskerChallenge":
        if not query_commitment:
            raise ValueError("query_commitment is required")
        return cls(nonce=os.urandom(16).hex(), query_commitment=query_commitment)

    def binding(self) -> str:
        """The value the expert must echo/attest — binds this query + nonce."""
        return _sha256(f"{self.nonce}|{self.query_commitment}")


@dataclass(frozen=True)
class ExecutionReceipt:
    """Returned by the expert alongside the answer; verified offline by the asker."""

    tier: str
    challenge_binding: str
    response_hash: str
    attestation: str | None = None  # TEE signature for ATTESTED; None for SOFT


def make_soft_receipt(challenge: AskerChallenge, answer: str) -> ExecutionReceipt:
    return ExecutionReceipt(
        tier=HonestyTier.SOFT.value,
        challenge_binding=challenge.binding(),
        response_hash=_sha256(answer),
    )


def make_attested_receipt(
    challenge: AskerChallenge,
    answer: str,
    tee_sign: Callable[[str], str],
) -> ExecutionReceipt:
    """Cloud-TEE expert: the TEE signs {binding | response_hash}."""
    response_hash = _sha256(answer)
    payload = f"{challenge.binding()}|{response_hash}"
    return ExecutionReceipt(
        tier=HonestyTier.ATTESTED.value,
        challenge_binding=challenge.binding(),
        response_hash=response_hash,
        attestation=tee_sign(payload),
    )


@dataclass(frozen=True)
class HonestyVerdict:
    ok: bool
    tier: str
    hard_proof: bool          # True only when a TEE attestation verified
    degraded_trust: bool      # True for the soft tier (reputation/audit, not crypto)
    reason: str | None = None


def verify_receipt(
    receipt: ExecutionReceipt,
    challenge: AskerChallenge,
    answer: str,
    *,
    tee_verify: Callable[[str, str], bool] | None = None,
) -> HonestyVerdict:
    """Asker-side offline check. Binds the answer to *this* query + nonce, then —
    for the attested tier — verifies the TEE signature for a hard guarantee."""

    if receipt.challenge_binding != challenge.binding():
        return HonestyVerdict(False, receipt.tier, False, True, "challenge_mismatch")
    if receipt.response_hash != _sha256(answer):
        return HonestyVerdict(False, receipt.tier, False, True, "answer_hash_mismatch")

    if receipt.tier == HonestyTier.ATTESTED.value:
        if tee_verify is None or not receipt.attestation:
            return HonestyVerdict(False, receipt.tier, False, False, "missing_attestation")
        payload = f"{receipt.challenge_binding}|{receipt.response_hash}"
        if not tee_verify(payload, receipt.attestation):
            return HonestyVerdict(False, receipt.tier, False, False, "bad_attestation")
        return HonestyVerdict(True, receipt.tier, hard_proof=True, degraded_trust=False)

    # SOFT: structurally bound to the query, but trust is reputation + spot-audit,
    # not a cryptographic proof. degraded_trust=True so the asker knows.
    return HonestyVerdict(True, receipt.tier, hard_proof=False, degraded_trust=True)
