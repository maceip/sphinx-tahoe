"""ERC-8004 Validation Registry–aligned execution attestation for P-OR exits.

Off-chain documents mirror EIP-8004 ``validationRequest`` / ``validationResponse``
fields (``requestURI``, ``requestHash``, ``response``, ``responseURI``,
``responseHash``, ``tag``). Relays never parse these; only the exit expert builds
them when the envelope asks for proof-of-execution.

Evidence is scoped to **runtime execution** (TLS/API call to the upstream model),
not input provenance or on-chain reputation (Assay-style stake scores stay
orthogonal).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Mapping, Sequence

from .envelope import PROOF_NONE, PROOF_TLS_EXECUTION, PromptRequestEnvelope

# EIP-8004 validationResponse.tag — versioned tenet profile
TAG_TENET_TLS_EXECUTION_V0 = "tenet.tls_execution.v0"

EVIDENCE_HARNESS = "harness"
EVIDENCE_ZKTLS = "zktls"
EVIDENCE_TEE = "tee"

CLAIM_RUNTIME_EXECUTION = "runtime_execution"
CLAIM_INPUT_PROVENANCE = "input_provenance"

REQUEST_DOC_TYPE = "https://tenet.dev/por/validation-request/v0"
RESPONSE_DOC_TYPE = "https://tenet.dev/por/validation-response/v0"


def requires_execution_attestation(envelope: PromptRequestEnvelope) -> bool:
    return any(req != PROOF_NONE for req in envelope.proof_requirements)


def requires_tls_attestation(envelope: PromptRequestEnvelope) -> bool:
    return PROOF_TLS_EXECUTION in envelope.proof_requirements


@dataclass(frozen=True)
class ValidationSubject:
    """Who/what is being validated — maps to ERC-8004 Magicians evidence-layer shape."""

    request_id: str
    peer_id: str
    principal: str | None = None
    agent_registry: str | None = None
    agent_id: str | None = None
    policy_hash: str | None = None
    code_measurement: str | None = None
    delegation_scope: str | None = None
    chain_id: int | None = None
    nonce: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "request_id": self.request_id,
            "peer_id": self.peer_id,
        }
        if self.principal is not None:
            out["principal"] = self.principal
        if self.agent_registry is not None:
            out["agent_registry"] = self.agent_registry
        if self.agent_id is not None:
            out["agent_id"] = self.agent_id
        if self.policy_hash is not None:
            out["policy_hash"] = self.policy_hash
        if self.code_measurement is not None:
            out["code_measurement"] = self.code_measurement
        if self.delegation_scope is not None:
            out["delegation_scope"] = self.delegation_scope
        if self.chain_id is not None:
            out["chain_id"] = self.chain_id
        if self.nonce is not None:
            out["nonce"] = self.nonce
        return out


@dataclass(frozen=True)
class ExecutionEvidence:
    evidence_family: str
    claim: str
    peer_id: str
    provider_mode: str
    llm_called: bool
    request_id: str
    prompt_sha256: str
    response_sha256: str
    upstream_host: str | None = None
    exportable_tls: dict[str, object] | None = None
    threshold_verifiers: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "evidence_family": self.evidence_family,
            "claim": self.claim,
            "peer_id": self.peer_id,
            "provider_mode": self.provider_mode,
            "llm_called": self.llm_called,
            "request_id": self.request_id,
            "prompt_sha256": self.prompt_sha256,
            "response_sha256": self.response_sha256,
        }
        if self.upstream_host is not None:
            out["upstream_host"] = self.upstream_host
        if self.exportable_tls is not None:
            out["exportable_tls"] = self.exportable_tls
        if self.threshold_verifiers:
            out["threshold_verifiers"] = list(self.threshold_verifiers)
        return out


def commitment_hash(payload: str | bytes) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return "0x" + sha256(payload).hexdigest()


def _canonical_json(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def build_request_document(
    envelope: PromptRequestEnvelope,
    *,
    peer_id: str,
    subject: ValidationSubject | None = None,
) -> dict[str, object]:
    intent = dict(envelope.intent_descriptor)
    subj = subject or ValidationSubject(
        request_id=envelope.request_id,
        peer_id=peer_id,
        agent_registry=_intent_str(intent, "agent_registry"),
        agent_id=_intent_str(intent, "agent_id"),
        policy_hash=_intent_str(intent, "policy_hash"),
        code_measurement=_intent_str(intent, "code_measurement"),
        delegation_scope=_intent_str(intent, "delegation_scope"),
        chain_id=_intent_int(intent, "chain_id"),
        nonce=_intent_str(intent, "nonce"),
        principal=_intent_str(intent, "principal"),
    )
    return {
        "type": REQUEST_DOC_TYPE,
        "subject": subj.to_dict(),
        "envelope": {
            "version": envelope.version,
            "request_id": envelope.request_id,
            "mode": envelope.mode,
            "proof_requirements": list(envelope.proof_requirements),
            "intent_descriptor": intent,
            "provider_request": dict(envelope.provider_request),
        },
        "evidence_expectations": list(envelope.proof_requirements),
    }


def build_response_document(
    evidence: ExecutionEvidence,
    *,
    request_hash: str,
) -> dict[str, object]:
    return {
        "type": RESPONSE_DOC_TYPE,
        "request_hash": request_hash,
        "evidence": evidence.to_dict(),
        "notes": _evidence_notes(evidence),
    }


def build_execution_attestation(
    envelope: PromptRequestEnvelope,
    *,
    peer_id: str,
    response_text: str,
    provider_mode: str,
    llm_called: bool,
    upstream_host: str | None = None,
    subject: ValidationSubject | None = None,
    exportable_tls: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build off-chain bundle + ERC-8004 field names for one expert execution."""
    intent = envelope.intent_descriptor
    prompt_sha = str(intent.get("prompt_sha256") or sha256(envelope.prompt_text().encode()).hexdigest())
    response_sha = sha256(response_text.encode("utf-8")).hexdigest()

    family = EVIDENCE_HARNESS if provider_mode == "harness" else EVIDENCE_ZKTLS
    if exportable_tls is not None:
        family = EVIDENCE_ZKTLS

    evidence = ExecutionEvidence(
        evidence_family=family,
        claim=CLAIM_RUNTIME_EXECUTION,
        peer_id=peer_id,
        provider_mode=provider_mode,
        llm_called=llm_called,
        request_id=envelope.request_id,
        prompt_sha256=prompt_sha,
        response_sha256=response_sha,
        upstream_host=upstream_host,
        exportable_tls=exportable_tls,
    )

    request_doc = build_request_document(envelope, peer_id=peer_id, subject=subject)
    request_body = _canonical_json(request_doc)
    req_hash = commitment_hash(request_body)

    response_doc = build_response_document(evidence, request_hash=req_hash)
    response_body = _canonical_json(response_doc)
    resp_hash = commitment_hash(response_body)

    # Harness: score 100 with synthetic tag; production zktls should use validator policy
    response_score = 100 if family == EVIDENCE_HARNESS else 0

    request_uri = f"por://attestation/request/{envelope.request_id}"
    response_uri = f"por://attestation/response/{envelope.request_id}"

    return {
        "registry_profile": "eip-8004-validation-registry",
        "validation_request": {
            "requestURI": request_uri,
            "requestHash": req_hash,
            "agentId": _intent_str(dict(intent), "agent_id"),
        },
        "validation_response": {
            "requestHash": req_hash,
            "response": response_score,
            "responseURI": response_uri,
            "responseHash": resp_hash,
            "tag": TAG_TENET_TLS_EXECUTION_V0,
        },
        "request_document": request_doc,
        "response_document": response_doc,
    }


def stream_done_payload(
    seq: int,
    *,
    attestation: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"seq": seq, "data": "", "done": True}
    if attestation is not None:
        payload["attestation"] = attestation
    return payload


def maybe_build_attestation(
    envelope: PromptRequestEnvelope,
    *,
    peer_id: str,
    response_text: str,
    provider_mode: str,
    llm_called: bool,
    upstream_host: str | None = None,
) -> dict[str, object] | None:
    if not requires_execution_attestation(envelope):
        return None
    if requires_tls_attestation(envelope) and provider_mode == "harness":
        # Still emit harness evidence so wire/tests work before TLSNotary lands
        pass
    return build_execution_attestation(
        envelope,
        peer_id=peer_id,
        response_text=response_text,
        provider_mode=provider_mode,
        llm_called=llm_called,
        upstream_host=upstream_host,
    )


def _evidence_notes(evidence: ExecutionEvidence) -> str:
    if evidence.evidence_family == EVIDENCE_HARNESS:
        return "Synthetic harness binding; not a TLSNotary proof."
    if evidence.llm_called and evidence.exportable_tls is None:
        return "Execution occurred; exportable TLS proof not yet attached."
    return "Exportable TLS evidence present."


def _intent_str(intent: Mapping[str, object], key: str) -> str | None:
    val = intent.get(key)
    return str(val) if val is not None else None


def _intent_int(intent: Mapping[str, object], key: str) -> int | None:
    val = intent.get(key)
    if val is None:
        return None
    return int(val)
