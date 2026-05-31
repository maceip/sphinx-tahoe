"""Versioned Layer 7 request envelopes for P-OR.

The envelope is the payload delivered to the selected expert/exit peer. Relays
carry it as opaque bytes. Future prompt-hiding or proof-of-execution work should
change this envelope payload mode, not the relay packet format.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Sequence
from uuid import uuid4


APP_ENVELOPE_VERSION = "por.app.v1"
VISIBLE_PROMPT_V1 = "visible_prompt_v1"
CONFIDENTIAL_PROMPT_V1 = "confidential_prompt_v1"
HYBRID_RETURN_PATH_V2 = "hybrid_return_path_v2"
PROOF_NONE = "none"
MPC_SESSION_V0 = "por.mpc_session.v0"
MPC_MODE_INLINE_2P = "inline_2p_v0"


def _default_streaming_return_descriptor() -> dict[str, object]:
    from sphinxmix.ta_claims import streaming_return_descriptor

    return streaming_return_descriptor(mode=HYBRID_RETURN_PATH_V2)


@dataclass(frozen=True)
class PromptRequestEnvelope:
    version: str
    request_id: str
    selected_peer_id: str | None
    mode: str
    provider_request: dict[str, object]
    intent_descriptor: dict[str, object]
    prompt_payload: dict[str, object]
    return_descriptor: dict[str, object]
    proof_requirements: tuple[str, ...] = (PROOF_NONE,)
    payment_terms: dict[str, object] | None = None
    mpc_session: dict[str, object] | None = None
    client_extensions: tuple[str, ...] = field(default_factory=tuple)
    privacy_warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def visible_prompt(
        cls,
        prompt: str,
        selected_peer_id: str | None,
        requested_expertise: str | None = None,
        provider_request: dict[str, object] | None = None,
        return_descriptor: dict[str, object] | None = None,
        proof_requirements: Sequence[str] = (PROOF_NONE,),
        payment_terms: dict[str, object] | None = None,
        mpc_session: dict[str, object] | None = None,
        client_extensions: Sequence[str] = (),
        privacy_warnings: Sequence[str] = (),
        request_id: str | None = None,
        extra_intent: dict[str, object] | None = None,
    ) -> "PromptRequestEnvelope":
        intent = {
            "requested_expertise": requested_expertise,
            "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        }
        if extra_intent:
            intent.update(extra_intent)

        return cls(
            version=APP_ENVELOPE_VERSION,
            request_id=request_id or uuid4().hex,
            selected_peer_id=selected_peer_id,
            mode=VISIBLE_PROMPT_V1,
            provider_request=provider_request or {"provider": "frontier", "stream": True},
            intent_descriptor=intent,
            prompt_payload={
                "content_type": "text/plain",
                "encoding": "utf-8",
                "text": prompt,
            },
            return_descriptor=return_descriptor or _default_streaming_return_descriptor(),
            proof_requirements=tuple(proof_requirements),
            payment_terms=dict(payment_terms) if payment_terms is not None else None,
            mpc_session=dict(mpc_session) if mpc_session is not None else None,
            client_extensions=tuple(client_extensions),
            privacy_warnings=tuple(privacy_warnings),
        )

    def to_json(self) -> str:
        self.validate()
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, data: str | bytes) -> "PromptRequestEnvelope":
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        raw = json.loads(data)
        envelope = cls(
            version=raw["version"],
            request_id=raw["request_id"],
            selected_peer_id=raw.get("selected_peer_id"),
            mode=raw["mode"],
            provider_request=dict(raw["provider_request"]),
            intent_descriptor=dict(raw["intent_descriptor"]),
            prompt_payload=dict(raw["prompt_payload"]),
            return_descriptor=dict(raw["return_descriptor"]),
            proof_requirements=tuple(raw.get("proof_requirements", (PROOF_NONE,))),
            payment_terms=(
                dict(raw["payment_terms"]) if raw.get("payment_terms") is not None else None
            ),
            mpc_session=(
                dict(raw["mpc_session"]) if raw.get("mpc_session") is not None else None
            ),
            client_extensions=tuple(raw.get("client_extensions", ())),
            privacy_warnings=tuple(raw.get("privacy_warnings", ())),
        )
        envelope.validate()
        return envelope

    def prompt_text(self) -> str:
        if self.mode != VISIBLE_PROMPT_V1:
            raise ValueError("prompt text is not available for confidential envelopes")
        text = self.prompt_payload.get("text")
        if not isinstance(text, str):
            raise ValueError("visible prompt envelope is missing text")
        return text

    def validate(self) -> None:
        if self.version != APP_ENVELOPE_VERSION:
            raise ValueError(f"unsupported envelope version: {self.version}")
        if self.mode not in {VISIBLE_PROMPT_V1, CONFIDENTIAL_PROMPT_V1}:
            raise ValueError(f"unsupported prompt mode: {self.mode}")
        if not self.request_id:
            raise ValueError("request_id is required")
        if "mode" not in self.return_descriptor:
            raise ValueError("return_descriptor.mode is required")
        if self.return_descriptor.get("stream") and "ta_claim" not in self.return_descriptor:
            raise ValueError(
                "streaming return_descriptor requires ta_claim (TA-3); "
                "use sphinxmix.ta_claims.streaming_return_descriptor()"
            )
        if self.mode == VISIBLE_PROMPT_V1 and "text" not in self.prompt_payload:
            raise ValueError("visible prompt envelope requires prompt_payload.text")
        if self.payment_terms is not None:
            from .payment import PaymentTerms

            PaymentTerms.from_dict(self.payment_terms).validate_against_envelope(self)
        if self.mpc_session is not None:
            _validate_mpc_session(self.mpc_session)


def build_inline_mpc_session(
    *,
    verifier_peer_id: str,
    verifier_commitment: str | None = None,
) -> dict[str, object]:
    """Bind the live 2P MPC verifier (requesting client) before expert upstream."""
    session: dict[str, object] = {
        "type": MPC_SESSION_V0,
        "mode": MPC_MODE_INLINE_2P,
        "verifier_peer_id": verifier_peer_id,
    }
    if verifier_commitment is not None:
        session["verifier_commitment"] = verifier_commitment
    return session


def _validate_mpc_session(raw: dict[str, object]) -> None:
    if raw.get("type") != MPC_SESSION_V0:
        raise ValueError(f"unsupported mpc_session type: {raw.get('type')!r}")
    mode = raw.get("mode")
    if mode != MPC_MODE_INLINE_2P:
        raise ValueError(f"unsupported mpc_session mode: {mode!r}")
    verifier = raw.get("verifier_peer_id")
    if not isinstance(verifier, str) or not verifier:
        raise ValueError("mpc_session.verifier_peer_id is required")

