"""Conditional settlement via base ``payment_terms`` on ``por.app.v1`` envelopes.

Pay-in → execute → proof generation (PGP) → payout (Şen et al., ePrint 2026/277).
Supports ERC-8004-aligned stake collateral and network-sponsored service fees
(gas + expert fee) without user-mounted escrow per job.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from .envelope import PromptRequestEnvelope
from .execution import release_predicate_for_provider

PAYMENT_TERMS_V0 = "por.payment_terms.v0"

# Legacy / strict escrow path
SCHEME_ZKTLS_CONDITIONAL = "zktls_conditional_v0"
# Network (tenet) sponsors gas + expert fee — custom service paymaster pattern
SCHEME_SPONSORED_SERVICE = "sponsored_service_v0"
# Expert ERC-8004 agent stake covers job (Assay-style collateral)
SCHEME_ERC8004_STAKE = "erc8004_stake_v0"
# 8183 job id in pay_in.ref — optional composition
SCHEME_ERC8183_JOB = "erc8183_job_v0"

SUPPORTED_SCHEMES = frozenset(
    {
        SCHEME_ZKTLS_CONDITIONAL,
        SCHEME_SPONSORED_SERVICE,
        SCHEME_ERC8004_STAKE,
        SCHEME_ERC8183_JOB,
    }
)

STATUS_PAY_IN_REQUIRED = "pay_in_required"
STATUS_PAY_IN_VERIFIED = "pay_in_verified"
STATUS_EXECUTED = "executed"
STATUS_PROOF_DUE = "proof_due"
STATUS_PAYOUT_PENDING = "payout_pending"
STATUS_PAYOUT_RELEASED = "payout_released"
STATUS_FAILED = "failed"

DEFAULT_SPONSOR_COVERS = ("gas", "expert_fee")


@dataclass(frozen=True)
class PaymentTerms:
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
        if scheme not in SUPPORTED_SCHEMES:
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


def _payment_terms_binding_material(
    raw: Mapping[str, object],
) -> dict[str, object]:
    """Canonical pay-in/payout/release for binding (exclude self-referential hash)."""
    return {k: v for k, v in raw.items() if k != "request_binding"}


def request_binding_hash(
    envelope: PromptRequestEnvelope,
    *,
    pending_payment_terms: Mapping[str, object] | None = None,
) -> str:
    """Hash job identity: prompt route, settlement terms, and MPC verifier binding."""
    material: dict[str, object] = {
        "version": envelope.version,
        "request_id": envelope.request_id,
        "selected_peer_id": envelope.selected_peer_id,
        "mode": envelope.mode,
        "intent_descriptor": envelope.intent_descriptor,
        "prompt_sha256": envelope.intent_descriptor.get("prompt_sha256"),
        "provider_request": envelope.provider_request,
    }
    terms_raw = pending_payment_terms if pending_payment_terms is not None else envelope.payment_terms
    if terms_raw is not None:
        material["payment_terms"] = _payment_terms_binding_material(terms_raw)
    if envelope.mpc_session is not None:
        material["mpc_session"] = envelope.mpc_session
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
    scheme: str,
    pay_in: dict[str, object],
    payout: dict[str, object],
    release: dict[str, object] | None = None,
    not_after: int | None = None,
) -> dict[str, object]:
    if release is None:
        mode = str(envelope.provider_request.get("provider", "harness"))
        provider_mode = mode if mode in {"anthropic", "openai", "harness"} else "harness"
        release = release_predicate_for_provider(provider_mode)
    pending: dict[str, object] = {
        "type": PAYMENT_TERMS_V0,
        "scheme": scheme,
        "pay_in": pay_in,
        "payout": payout,
        "release": release,
    }
    if not_after is not None:
        pending["not_after"] = not_after
    binding = request_binding_hash(envelope, pending_payment_terms=pending)
    return PaymentTerms(
        type=PAYMENT_TERMS_V0,
        scheme=scheme,
        request_binding=binding,
        pay_in=pay_in,
        payout=payout,
        release=release,
        not_after=not_after,
    ).to_dict()


def build_sponsored_service_terms(
    envelope: PromptRequestEnvelope,
    *,
    sponsor_id: str,
    sponsor_address: str | None = None,
    expert_fee_atomic: str = "0",
    asset: str = "USDC",
    verified: bool = True,
) -> dict[str, object]:
    """Network sponsor covers gas (4337 paymaster) + expert fee (service paymaster)."""
    pay_in: dict[str, object] = {
        "sponsor": {
            "id": sponsor_id,
            "address": sponsor_address,
            "covers": list(DEFAULT_SPONSOR_COVERS),
            "gas_paymaster": "erc4337",
            "service_paymaster": "tenet_sponsor_v0",
        },
        "verified": verified,
        "expert_fee": {"amount": expert_fee_atomic, "asset": asset},
    }
    return build_payment_terms(
        envelope,
        scheme=SCHEME_SPONSORED_SERVICE,
        pay_in=pay_in,
        payout={
            "payee": envelope.selected_peer_id,
            "amount": expert_fee_atomic,
            "asset": asset,
        },
    )


def build_erc8004_stake_terms(
    envelope: PromptRequestEnvelope,
    *,
    agent_registry: str,
    agent_id: str,
    stake_wei: str,
    min_stake_wei: str | None = None,
    stake_sufficient: bool = True,
    expert_fee_atomic: str = "0",
    asset: str = "USDC",
) -> dict[str, object]:
    """Provider collateral via ERC-8004 identity + stake (Assay-style path)."""
    pay_in: dict[str, object] = {
        "stake": {
            "agent_registry": agent_registry,
            "agent_id": agent_id,
            "stake_wei": stake_wei,
            "min_stake_wei": min_stake_wei or stake_wei,
            "stake_sufficient": stake_sufficient,
        },
        "verified": stake_sufficient,
    }
    intent_extra = {
        "agent_registry": agent_registry,
        "agent_id": agent_id,
    }
    return build_payment_terms(
        envelope,
        scheme=SCHEME_ERC8004_STAKE,
        pay_in=pay_in,
        payout={
            "payee": envelope.selected_peer_id,
            "amount": expert_fee_atomic,
            "asset": asset,
        },
    )


def build_default_tenet_payment_terms(
    envelope: PromptRequestEnvelope,
    *,
    prefer_stake: bool = True,
) -> dict[str, object]:
    """Prefer 8004 stake when agent_id present; else network-sponsored path."""
    intent = envelope.intent_descriptor
    registry = intent.get("agent_registry")
    agent_id = intent.get("agent_id")
    if prefer_stake and registry and agent_id:
        return build_erc8004_stake_terms(
            envelope,
            agent_registry=str(registry),
            agent_id=str(agent_id),
            stake_wei=str(intent.get("stake_wei") or "0"),
            stake_sufficient=bool(intent.get("stake_sufficient", True)),
        )
    sponsor = str(intent.get("sponsor_id") or os.environ.get("TENET_SPONSOR_ID", "tenet-network"))
    return build_sponsored_service_terms(
        envelope,
        sponsor_id=sponsor,
        sponsor_address=os.environ.get("TENET_SPONSOR_ADDRESS"),
        verified=True,
    )


def verify_pay_in(terms: PaymentTerms, *, mode: str) -> bool:
    if mode in {"harness", "trust"}:
        return _scheme_pay_in_present(terms)
    if mode != "strict":
        return False

    if terms.scheme == SCHEME_SPONSORED_SERVICE:
        sponsor = terms.pay_in.get("sponsor")
        return (
            isinstance(sponsor, dict)
            and terms.pay_in.get("verified") is True
            and bool(sponsor.get("covers"))
        )
    if terms.scheme == SCHEME_ERC8004_STAKE:
        stake = terms.pay_in.get("stake")
        return (
            isinstance(stake, dict)
            and stake.get("stake_sufficient") is True
            and terms.pay_in.get("verified") is True
        )
    if terms.scheme == SCHEME_ERC8183_JOB:
        return terms.pay_in.get("job_funded") is True
    if terms.scheme == SCHEME_ZKTLS_CONDITIONAL:
        return terms.pay_in.get("verified") is True
    return False


def _scheme_pay_in_present(terms: PaymentTerms) -> bool:
    if terms.scheme == SCHEME_SPONSORED_SERVICE:
        return isinstance(terms.pay_in.get("sponsor"), dict)
    if terms.scheme == SCHEME_ERC8004_STAKE:
        return isinstance(terms.pay_in.get("stake"), dict)
    if terms.scheme == SCHEME_ERC8183_JOB:
        return bool(terms.pay_in.get("job_id") or terms.pay_in.get("ref"))
    return bool(terms.pay_in)


def payment_verify_mode() -> str:
    return os.environ.get("POR_PAYMENT_VERIFY", "harness").strip().lower() or "harness"


def require_pay_in_before_execution(envelope: PromptRequestEnvelope) -> PaymentTerms | None:
    terms = payment_terms_from_envelope(envelope)
    if terms is None:
        return None
    if not verify_pay_in(terms, mode=payment_verify_mode()):
        raise PaymentRequiredError(
            "pay_in not verified; expert will not call upstream until funding path is satisfied",
            terms=terms.to_dict(),
        )
    return terms


class PaymentRequiredError(RuntimeError):
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
    from .execution import upstream_host

    response_sha = sha256(response_text.encode("utf-8")).hexdigest()
    status = STATUS_PAY_IN_REQUIRED if not pay_in_verified else STATUS_PROOF_DUE

    return {
        "type": "por.payment_settlement.v0",
        "request_id": envelope.request_id,
        "request_binding": terms.request_binding,
        "scheme": terms.scheme,
        "status": status,
        "pay_in": {
            "verified": pay_in_verified,
            "ref": terms.pay_in.get("ref") or terms.pay_in.get("job_id"),
            "path": terms.scheme,
        },
        "execution": {
            "peer_id": peer_id,
            "provider_mode": provider_mode,
            "response_sha256": response_sha,
            "upstream_host": upstream_host(provider_mode),
            "llm_called": provider_mode not in {"harness", "frontier"},
        },
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


def _canonical_json(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
