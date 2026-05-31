"""Pluggable TLS execution provers behind ``execution_trace`` / ``proof_obligation``.

The wire "front end" is ``por.execution`` (VET-style trace + Şen PGP slot). This
module is the back end: TLSNotary today, other dx-DCTLS/MPC-TLS implementations
later. Relays never see prover choice.
"""

from __future__ import annotations

import os
from typing import Mapping

PROVER_HARNESS = "harness"
PROVER_TLSNOTARY = "tlsnotary"

# Cryptographic profile (stable on the wire)
PROOF_SYSTEM_DX_DCTLS_EXPORT = "dx_dctls_export.v0"


def prover_backend() -> str:
    return os.environ.get("POR_TLS_PROVER", PROVER_HARNESS).strip().lower() or PROVER_HARNESS


def generate_exportable_proof(
    *,
    request_id: str,
    upstream_host: str | None,
    response_sha256: str,
    session_material: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Produce ``exportable_tls`` payload for ``proof_obligation`` after upstream HTTP."""
    backend = prover_backend()
    if backend == PROVER_HARNESS:
        return _harness_proof(request_id=request_id, response_sha256=response_sha256)
    if backend == PROVER_TLSNOTARY:
        return _tlsnotary_proof(
            request_id=request_id,
            upstream_host=upstream_host,
            response_sha256=response_sha256,
            session_material=session_material,
        )
    raise ValueError(f"unsupported POR_TLS_PROVER: {backend!r}")


def proof_obligation_status_for_backend(*, harness_mode: bool) -> str:
    if harness_mode or prover_backend() == PROVER_HARNESS:
        return "harness_stub"
    if prover_backend() == PROVER_TLSNOTARY:
        return "pending"
    return "pending"


def _harness_proof(*, request_id: str, response_sha256: str) -> dict[str, object]:
    return {
        "prover": PROVER_HARNESS,
        "proof_system": PROOF_SYSTEM_DX_DCTLS_EXPORT,
        "request_id": request_id,
        "response_sha256": response_sha256,
        "exportable": None,
        "notes": "Set POR_TLS_PROVER=tlsnotary for real TLSNotary PGP output.",
    }


def _tlsnotary_proof(
    *,
    request_id: str,
    upstream_host: str | None,
    response_sha256: str,
    session_material: Mapping[str, object] | None,
) -> dict[str, object]:
    """TLSNotary integration point (server-side expert HTTP to allowed hosts)."""
    # Session capture and notarization run in the expert/coordinator process;
    # wire the TLSNotary CLI or library here when enabled.
    if session_material is None:
        return {
            "prover": PROVER_TLSNOTARY,
            "proof_system": PROOF_SYSTEM_DX_DCTLS_EXPORT,
            "request_id": request_id,
            "upstream_host": upstream_host,
            "response_sha256": response_sha256,
            "exportable": None,
            "status": "awaiting_session_capture",
            "notes": (
                "TLSNotary prover selected; attach session_material from the "
                "expert upstream HTTP client after the LLM call."
            ),
        }
    return {
        "prover": PROVER_TLSNOTARY,
        "proof_system": PROOF_SYSTEM_DX_DCTLS_EXPORT,
        "request_id": request_id,
        "upstream_host": upstream_host,
        "response_sha256": response_sha256,
        "exportable": dict(session_material),
        "status": "ready",
    }
