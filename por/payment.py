"""Conditional settlement via base ``payment_terms`` on ``por.app.v1`` envelopes.

Maps the pay-in → execute → proof-generation (PGP) → payout pattern from
collusion-minimized / exportable TLS attestation work (Şen et al., ePrint
2026/277) onto the existing expert path. This is **not** a wire extension:
relays stay ignorant; only client and expert interpret ``payment_terms``.

zkTLS / dx-DCTLS + threshold verifiers are **off-envelope** obligations referenced
by hash and URI. The mixnet carries the job terms; settlement coordinators verify
pay-in and release payout when an exportable proof satisfies ``release``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from .envelope import PromptRequestEnvelope

PAYMENT_TERMS_V0 = "por.payment_terms.v0"
SCHEME_ZKTLS_CONDITIONAL = "zktls_conditional_v0"

STATUS_PAY_IN_REQUIRED = "pay_in_required"
STATUS_PAY_IN_VERIFIED = "pay_in_verified"
STATUS_EXECUTED = "executed"
STATUS_PROOF_DUE = "proof_due"
STATUS_PAYOUT_PENDING = "payout_pending"
STATUS_PAYOUT_RELEASED = "payout_released"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class PaymentTerms:
    """Client-declared conditional payment for one expert execution."""

    type: str
    scheme: str
    request_binding: str
    pay_in: dict[str, object]
    payout: dict[str, object]
    release: dict[str, object]
    not_before: int | None = None
    not_after: int | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "PaymentTerms":
        if raw.get("type") != PAYMENT_TERMS_V0:
            raise ValueError(f"unsupported payment_terms type: {raw.get('type')!r}")
        scheme = str(raw.get("scheme", ""))
        if scheme != SCHEME_ZKTLS_CONDITIONAL:
            raise ValueError(f"unsupported payment scheme: {scheme!r}")
        binding = raw.get("request_binding")
        if not isinstance(binding, str) or not binding:
            raise ValueError("payment_terms.request_binding is required")
        for key in ("pay_in", "payout", "release"):
            block = raw.get(key)
            if not isinstance(block, dict):
                raise ValueError(f"payment_terms.{key} must be an object")
        nb = raw.get("not_before")
        na = raw.get("not_after")
        return cls(
            type=PAYMENT_TERMS_V0,
            scheme=scheme,
            request_binding=binding,
            pay_in=dict(raw["pay_in"]),  # type: ignore[arg-type]
            payout=dict(raw["payout"]),  # type: ignore[arg-type]
            release=dict(raw["release"]),  # type: ignore[arg-type]
            not_before=int(nb) if nb is not None else None,
            not_after=int(na) if na is not None else None,
        )

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "type": self.type,
            "scheme": self.scheme,
            "request_binding": self.request_binding,
            "pay_in": self.pay_in,
            "payout": self.payout,
            "release": self.release,
        }
        if self.not_before is not None:
            out["not_before"] = self.not_before
        if self.not_after is not None:
            out["not_after"] = self.not_after
        return out

    def validate_against_envelope(self, envelope: PromptRequestEnvelope) -> None:
        expected = request_binding_hash(envelope)
        if self.request_binding != expected:
            raise ValueError(
                "payment_terms.request_binding does not match envelope "
                f"(expected {expected}, got {self.request_binding})"
            )


def request_binding_hash(envelope: PromptRequestEnvelope) -> str:
    """Commitment over stable request fields (pay-in locks this job)."""
    material = {
        "version": envelope.version,
        "request_id": envelope.request_id,
        "selected_peer_id": envelope.selected_peer_id,
        "mode": envelope.mode,
        "intent_descriptor": envelope.intent_descriptor,
        "prompt_sha256": envelope.intent_descriptor.get("prompt_sha256"),
        "provider_request": envelope.provider_request,
    }
    return "0x" + sha256(_canonical_json(material).encode()).hexdigest()


def payment_terms_from_envelope(envelope: PromptRequestEnvelope) -> PaymentTerms | None:
    raw = envelope.payment_terms
    if raw is None:
        return None
    terms = PaymentTerms.from_dict(raw)
    terms.validate_against_envelope(envelope)
    return terms


def build_payment_terms(
    envelope: PromptRequestEnvelope,
    *,
    pay_in: dict[str, object],
    payout: dict[str, object],
    release: dict[str, object],
    not_after: int | None = None,
) -> dict[str, object]:
    """Helper for clients attaching conditional settlement to a request."""
    binding = request_binding_hash(envelope)
    terms = PaymentTerms(
        type=PAYMENT_TERMS_V0,
        scheme=SCHEME_ZKTLS_CONDITIONAL,
        request_binding=binding,
        pay_in=pay_in,
        payout=payout,
        release=release,
        not_after=not_after,
    )
    return terms.to_dict()


def verify_pay_in(terms: PaymentTerms, *, mode: str) -> bool:
    """Return whether pay-in is satisfied before the expert calls upstream.

    ``harness`` and ``trust`` accept any well-formed pay_in block for dev.
    ``strict`` requires ``pay_in.verified == true`` (set by client/coordinator).
    """
    if mode in {"harness", "trust"}:
        return bool(terms.pay_in)
    if mode == "strict":
        return terms.pay_in.get("verified") is True
    return False


def payment_verify_mode() -> str:
    import os

    return os.environ.get("POR_PAYMENT_VERIFY", "harness").strip().lower() or "harness"


def require_pay_in_before_execution(envelope: PromptRequestEnvelope) -> PaymentTerms | None:
    terms = payment_terms_from_envelope(envelope)
    if terms is None:
        return None
    if not verify_pay_in(terms, mode=payment_verify_mode()):
        raise PaymentRequiredError(
            "pay_in not verified; expert will not call upstream until premium is locked",
            terms=terms.to_dict(),
        )
    return terms


class PaymentRequiredError(RuntimeError):
    """Raised when execution proceeds without satisfied pay-in."""

    def __init__(self, message: str, *, terms: dict[str, object]):
        super().__init__(message)
        self.terms = terms


def build_settlement_receipt(
    envelope: PromptRequestEnvelope,
    *,
    peer_id: str,
    response_text: str,
    provider_mode: str,
    terms: PaymentTerms,
    pay_in_verified: bool,
) -> dict[str, object]:
    """Post-execution settlement state returned on the final stream frame."""
    response_sha = sha256(response_text.encode("utf-8")).hexdigest()
    upstream = _upstream_host(provider_mode)
    proof_slot = {
        "type": "exportable_tls.v0",
        "status": "pending",
        "proof_uri": None,
        "proof_hash": None,
        "notes": (
            "Submit dx-DCTLS / zkTLS exportable attestation in PGP; "
            "threshold verifiers release payout per payment_terms.release"
        ),
    }
    if provider_mode == "harness":
        proof_slot["status"] = "harness_stub"
        proof_slot["notes"] = "Harness: no TLS transcript; payout remains off-chain/manual"

    if not pay_in_verified:
        status = STATUS_PAY_IN_REQUIRED
    elif provider_mode == "harness":
        status = STATUS_PROOF_DUE
    else:
        status = STATUS_PROOF_DUE

    return {
        "type": "por.payment_settlement.v0",
        "request_id": envelope.request_id,
        "request_binding": terms.request_binding,
        "scheme": terms.scheme,
        "status": status,
        "pay_in": {"verified": pay_in_verified, "ref": terms.pay_in.get("ref")},
        "execution": {
            "peer_id": peer_id,
            "provider_mode": provider_mode,
            "response_sha256": response_sha,
            "upstream_host": upstream,
            "llm_called": provider_mode not in {"harness", "frontier"},
        },
        "proof_obligation": proof_slot,
        "payout": {
            "status": STATUS_PAYOUT_PENDING if pay_in_verified else STATUS_FAILED,
            "payee": terms.payout.get("payee"),
            "amount": terms.payout.get("amount"),
            "asset": terms.payout.get("asset"),
        },
        "release_predicate": terms.release,
    }


def stream_done_payload(
    seq: int,
    *,
    settlement: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"seq": seq, "data": "", "done": True}
    if settlement is not None:
        payload["payment_settlement"] = settlement
    return payload


def _upstream_host(provider_mode: str) -> str | None:
    if provider_mode == "anthropic":
        return "api.anthropic.com"
    if provider_mode == "openai":
        return "api.openai.com"
    return None


def _canonical_json(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
