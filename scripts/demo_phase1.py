#!/usr/bin/env python3
"""Phase-1 demo: prepaid anonymous query token + two-tier execution honesty.

Self-contained (no network). Walks the whole story:
  pay -> issue prepaid tickets -> spend one (rate-limit) -> expert answers ->
  asker verifies execution honesty offline -> double-spend blocked.

Run:  python3 scripts/demo_phase1.py
"""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenet.vouchers import issue_voucher_batch, redeem_ticket
from tenet.honesty import (
    AskerChallenge,
    make_attested_receipt,
    make_soft_receipt,
    verify_receipt,
)


def line(c="-"):
    print(c * 64)


def main() -> int:
    issuer_secret = os.urandom(32)
    spent_nullifiers: set[str] = set()

    line("=")
    print(" tenet — Phase 1: paid, anonymous, honesty-checked queries")
    line("=")

    # 1. PAYMENT + ISSUANCE (Algorand x402 stand-in) --------------------------
    print("\n[1] PAY + ISSUE  (Algorand pre-pay stand-in)")
    pay_tx = "ALGO_" + os.urandom(6).hex()
    voucher = issue_voucher_batch(
        queries=3, issuer_secret=issuer_secret, pool="soup.expert~tenet", pay_tx=pay_tx,
    )
    print(f"    pre-paid tx (visible on chain): {pay_tx}")
    print(f"    issued {voucher.remaining()} prepaid tickets for pool {voucher.pool}")
    print(f"    tickets are random + MAC-signed; unlinkable to the payment")

    # 2. ASKER PREPARES A QUERY ----------------------------------------------
    print("\n[2] ASK  (asker forms a query + an unforceable challenge)")
    prompt = "What did Monet change about how light is represented?"
    query_commitment = hashlib.sha256(("soup.expert~tenet|" + prompt).encode()).hexdigest()[:16]
    challenge = AskerChallenge.issue(query_commitment)
    print(f"    prompt: {prompt!r}")
    print(f"    query_commitment: {query_commitment}")
    print(f"    fresh asker nonce: {challenge.nonce}   (expert cannot force/replay it)")

    # 3. SPEND A TICKET (rate-limit) -----------------------------------------
    print("\n[3] SPEND  (redeem one ticket to authorize the query)")
    ticket = voucher.tickets[0]
    voucher, nullifier = redeem_ticket(
        voucher, ticket.token, ticket.mac, issuer_secret, spent_nullifiers,
    )
    print(f"    spent ticket; nullifier burned: {nullifier[:16]}…")
    print(f"    remaining queries on voucher: {voucher.remaining()}")

    # 4. EXPERT ANSWERS (laptop = SOFT tier) ---------------------------------
    print("\n[4] ANSWER  (laptop expert — SOFT honesty tier)")
    answer = "Monet rendered light as discrete strokes of unmixed colour, "
    answer += "shifting with the time of day."
    soft_receipt = make_soft_receipt(challenge, answer)
    print(f"    answer: {answer!r}")
    print(f"    receipt tier: {soft_receipt.tier}  (no consumer TEE -> reputation + spot-audit)")

    # 5. ASKER VERIFIES OFFLINE ----------------------------------------------
    print("\n[5] VERIFY  (asker checks the receipt offline)")
    verdict = verify_receipt(soft_receipt, challenge, answer)
    print(f"    ok={verdict.ok}  tier={verdict.tier}  hard_proof={verdict.hard_proof}  "
          f"degraded_trust={verdict.degraded_trust}")
    print("    -> bound to THIS query+nonce; soft tier so trust = reputation/audit")

    # 6. DOUBLE-SPEND BLOCKED -------------------------------------------------
    print("\n[6] ABUSE  (replay the same ticket -> blocked)")
    try:
        redeem_ticket(voucher, ticket.token, ticket.mac, issuer_secret, spent_nullifiers)
        print("    !! double-spend SUCCEEDED — BUG")
        return 1
    except ValueError as exc:
        print(f"    double-spend rejected: {exc}")

    # 7. OPT-IN HARD TIER (cloud-TEE expert) ---------------------------------
    print("\n[7] HARD TIER  (opt-in cloud-TEE expert — ATTESTED)")
    tee_secret = b"cloud-tee-attestation-key"
    tee_sign = lambda p: hashlib.sha256(tee_secret + p.encode()).hexdigest()
    tee_verify = lambda p, s: s == hashlib.sha256(tee_secret + p.encode()).hexdigest()
    attested = make_attested_receipt(challenge, answer, tee_sign)
    hv = verify_receipt(attested, challenge, answer, tee_verify=tee_verify)
    print(f"    ok={hv.ok}  tier={hv.tier}  hard_proof={hv.hard_proof}  "
          f"degraded_trust={hv.degraded_trust}")
    print("    -> same flow, hard cryptographic provenance when the expert has a TEE")

    line("=")
    print(" demo complete: paid + anonymous + rate-limited + honesty-tiered")
    line("=")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
