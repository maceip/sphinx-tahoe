"""Unified expert response: execution trace + payment settlement on ``done`` frames."""

from __future__ import annotations

from .envelope import PromptRequestEnvelope
from .execution import build_execution_trace
from .payment import (
    PaymentTerms,
    build_settlement_receipt,
    payment_terms_from_envelope,
    stream_done_payload,
    verify_pay_in,
    payment_verify_mode,
)


def build_verifiable_completion(
    envelope: PromptRequestEnvelope,
    *,
    peer_id: str,
    response_text: str,
    provider_mode: str,
    terms: PaymentTerms | None,
    pay_in_verified: bool,
) -> dict[str, object]:
    """Payload fragments for the final streaming frame."""
    execution_trace = build_execution_trace(
        envelope,
        peer_id=peer_id,
        provider_mode=provider_mode,
        response_text=response_text,
    )
    out: dict[str, object] = {"execution_trace": execution_trace}
    if terms is not None:
        settlement = build_settlement_receipt(
            envelope,
            peer_id=peer_id,
            response_text=response_text,
            provider_mode=provider_mode,
            terms=terms,
            pay_in_verified=pay_in_verified,
        )
        # Align settlement proof slot with trace obligation
        settlement["proof_obligation"] = execution_trace["proof_obligation"]
        settlement["erc8004"] = _erc8004_settlement_hints(terms, pay_in_verified)
        out["payment_settlement"] = settlement
    return out


def stream_done_with_verification(
    seq: int,
    *,
    completion: dict[str, object] | None = None,
) -> dict[str, object]:
    settlement = None
    if completion is not None:
        raw = completion.get("payment_settlement")
        if isinstance(raw, dict):
            settlement = raw
    payload = stream_done_payload(seq, settlement=settlement)
    if completion is not None:
        for key, value in completion.items():
            if key != "payment_settlement":
                payload[key] = value
    return payload


def pay_in_verified_for_envelope(envelope: PromptRequestEnvelope) -> tuple[PaymentTerms | None, bool]:
    terms = payment_terms_from_envelope(envelope)
    if terms is None:
        return None, False
    ok = verify_pay_in(terms, mode=payment_verify_mode())
    return terms, ok


def _erc8004_settlement_hints(terms: PaymentTerms, pay_in_verified: bool) -> dict[str, object]:
    """Hooks for Validation / Reputation registries (EIP-8004)."""
    hint: dict[str, object] = {
        "registry_profile": "eip-8004",
        "payment_scheme": terms.scheme,
    }
    stake = terms.pay_in.get("stake")
    sponsor = terms.pay_in.get("sponsor")
    if isinstance(stake, dict):
        hint["stake_path"] = stake
    if isinstance(sponsor, dict):
        hint["sponsor_path"] = sponsor
    if pay_in_verified and terms.scheme.startswith("erc8004_stake"):
        hint["reputation_note"] = "On success, post validationResponse + optional feedback"
    return hint
