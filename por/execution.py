"""Verifiable execution traces for server-side LLM upstream calls (VET + Şen).

Tenet experts call exactly two black-box HTTPS tools today:

- ``api.anthropic.com`` (Claude)
- ``api.openai.com`` (Codex / OpenAI API)

Proof uses exportable TLS attestation (dx-DCTLS / zkTLS family; TLSNotary is the
default pluggable prover via ``por.prover``) with threshold validation (Şen et
al., ePrint 2026/277). Composition follows VET (Grigor et al., arXiv:2512.15892):
``execution_trace`` on the final stream frame is the front end; provers plug in
behind ``proof_obligation.exportable_tls``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from .envelope import PromptRequestEnvelope

EXECUTION_TRACE_V0 = "por.execution_trace.v0"
AID_FRAGMENT_V0 = "por.aid_fragment.v0"
PROOF_DX_DCTLS_EXPORT_V0 = "dx_dctls_export.v0"

# Expert process → vendor HTTPS (urllib/HTTP client), two hosts only
UPSTREAM_PROFILES: dict[str, dict[str, str]] = {
    "anthropic": {
        "host": "api.anthropic.com",
        "provider_mode": "anthropic",
        "tool_id": "llm.anthropic.messages",
    },
    "openai": {
        "host": "api.openai.com",
        "provider_mode": "openai",
        "tool_id": "llm.openai.chat_completions",
    },
}

DEFAULT_THRESHOLD_POLICY = {
    "model": "sen_coll_min_v0",
    "threshold": 2,
    "total_verifiers": 3,
    "notes": "DVRF session bind + TSS release; coordinator runs O(1) prover",
}


@dataclass(frozen=True)
class UpstreamProfile:
    host: str
    provider_mode: str
    tool_id: str


def upstream_profile(provider_mode: str) -> UpstreamProfile | None:
    raw = UPSTREAM_PROFILES.get(provider_mode)
    if raw is None:
        return None
    return UpstreamProfile(
        host=raw["host"],
        provider_mode=raw["provider_mode"],
        tool_id=raw["tool_id"],
    )


def upstream_host(provider_mode: str) -> str | None:
    profile = upstream_profile(provider_mode)
    return profile.host if profile else None


def build_aid_fragment(
    envelope: PromptRequestEnvelope,
    *,
    peer_id: str,
    provider_mode: str,
) -> dict[str, object]:
    """Minimal Agent Identity Document fragment for one expert execution."""
    profile = upstream_profile(provider_mode)
    tools: list[dict[str, object]] = []
    if profile is not None:
        tools.append(
            {
                "tool_id": profile.tool_id,
                "upstream_host": profile.host,
                "proof_system": PROOF_DX_DCTLS_EXPORT_V0,
                "transport": "https_server_side",
            }
        )
    return {
        "type": AID_FRAGMENT_V0,
        "request_id": envelope.request_id,
        "peer_id": peer_id,
        "envelope_version": envelope.version,
        "provider_request": dict(envelope.provider_request),
        "tools": tools,
        "framework": "vet_compositional",
    }


def build_tool_step(
    *,
    envelope: PromptRequestEnvelope,
    peer_id: str,
    provider_mode: str,
    response_text: str,
    step_index: int = 0,
) -> dict[str, object]:
    profile = upstream_profile(provider_mode)
    prompt_sha = str(envelope.intent_descriptor.get("prompt_sha256") or "")
    response_sha = sha256(response_text.encode("utf-8")).hexdigest()
    return {
        "step": step_index,
        "tool_id": profile.tool_id if profile else f"unknown.{provider_mode}",
        "upstream_host": profile.host if profile else None,
        "peer_id": peer_id,
        "request_id": envelope.request_id,
        "prompt_sha256": prompt_sha,
        "response_sha256": response_sha,
        "llm_called": provider_mode not in {"harness", "frontier"},
        "proof_system": PROOF_DX_DCTLS_EXPORT_V0 if profile else "none",
    }


def build_proof_obligation(
    *,
    envelope: PromptRequestEnvelope,
    provider_mode: str,
    response_text: str,
    harness: bool,
    session_material: dict[str, object] | None = None,
) -> dict[str, object]:
    """Şen-style PGP slot: pluggable prover fills ``exportable_tls``."""
    from .prover import generate_exportable_proof, proof_obligation_status_for_backend

    profile = upstream_profile(provider_mode)
    response_sha = sha256(response_text.encode("utf-8")).hexdigest()
    host = profile.host if profile else None
    exportable = generate_exportable_proof(
        request_id=envelope.request_id,
        upstream_host=host,
        response_sha256=response_sha,
        session_material=session_material,
    )
    obligation: dict[str, object] = {
        "type": PROOF_DX_DCTLS_EXPORT_V0,
        "status": proof_obligation_status_for_backend(harness_mode=harness or profile is None),
        "request_id": envelope.request_id,
        "upstream_host": host,
        "response_sha256": response_sha,
        "exportable_tls": exportable,
        "prover": exportable.get("prover"),
        "threshold_policy": dict(DEFAULT_THRESHOLD_POLICY),
        "validation_registry": _validation_registry_hint(envelope),
        "mpc_session": envelope.mpc_session,
        "pgp_notes": (
            "PGP: exportable TLS proof from configured prover (default TLSNotary); "
            "threshold validators release payout per Şen coll-min framework."
        ),
    }
    return obligation


def build_execution_trace(
    envelope: PromptRequestEnvelope,
    *,
    peer_id: str,
    provider_mode: str,
    response_text: str,
) -> dict[str, object]:
    aid = build_aid_fragment(envelope, peer_id=peer_id, provider_mode=provider_mode)
    step = build_tool_step(
        envelope=envelope,
        peer_id=peer_id,
        provider_mode=provider_mode,
        response_text=response_text,
    )
    harness = provider_mode == "harness"
    return {
        "type": EXECUTION_TRACE_V0,
        "request_id": envelope.request_id,
        "aid_fragment": aid,
        "steps": [step],
        "proof_obligation": build_proof_obligation(
            envelope=envelope,
            provider_mode=provider_mode,
            response_text=response_text,
            harness=harness,
        ),
    }


def release_predicate_for_provider(provider_mode: str) -> dict[str, object]:
    profile = upstream_profile(provider_mode)
    if profile is None:
        return {"predicate": "none"}
    return {
        "predicate": "dx_dctls_export",
        "upstream_host": profile.host,
        "tool_id": profile.tool_id,
        "bind": ["request_id", "prompt_sha256", "response_sha256"],
    }


def _validation_registry_hint(envelope: PromptRequestEnvelope) -> dict[str, object] | None:
    intent = envelope.intent_descriptor
    registry = intent.get("agent_registry")
    agent_id = intent.get("agent_id")
    if registry is None and agent_id is None:
        return None
    return {
        "agent_registry": registry,
        "agent_id": agent_id,
        "tag": "tenet.dx_dctls_execution.v0",
        "evidence_family": "runtime_execution",
    }


def canonical_json(obj: Mapping[str, object]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
