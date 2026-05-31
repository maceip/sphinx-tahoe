import os

from por.prover import (
    PROVER_TLSNOTARY,
    generate_exportable_proof,
    prover_backend,
)


def test_prover_default_harness():
    assert prover_backend() == "harness"


def test_tlsnotary_prover_without_session(monkeypatch):
    monkeypatch.setenv("POR_TLS_PROVER", PROVER_TLSNOTARY)
    out = generate_exportable_proof(
        request_id="abc",
        upstream_host="api.anthropic.com",
        response_sha256="deadbeef",
    )
    assert out["prover"] == PROVER_TLSNOTARY
    assert out["status"] == "awaiting_session_capture"


def test_tlsnotary_prover_with_session(monkeypatch):
    monkeypatch.setenv("POR_TLS_PROVER", PROVER_TLSNOTARY)
    out = generate_exportable_proof(
        request_id="abc",
        upstream_host="api.openai.com",
        response_sha256="cafe",
        session_material={"notary_proof": "stub"},
    )
    assert out["status"] == "ready"
    assert out["exportable"]["notary_proof"] == "stub"
