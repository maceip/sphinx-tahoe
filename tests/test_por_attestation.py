import json

from por.attestation import (
    TAG_TENET_TLS_EXECUTION_V0,
    build_execution_attestation,
    commitment_hash,
    maybe_build_attestation,
    requires_tls_attestation,
    stream_done_payload,
)
from por.envelope import PROOF_NONE, PROOF_TLS_EXECUTION, PromptRequestEnvelope
from por.provider import expert_reply_with_attestation


def test_commitment_hash_prefixed():
    h = commitment_hash('{"a":1}')
    assert h.startswith("0x")
    assert len(h) == 66


def test_requires_tls_when_proof_set():
    env = PromptRequestEnvelope.visible_prompt(
        prompt="hi",
        selected_peer_id="p1",
        proof_requirements=(PROOF_TLS_EXECUTION,),
    )
    assert requires_tls_attestation(env)


def test_no_attestation_when_proof_none():
    env = PromptRequestEnvelope.visible_prompt(prompt="hi", selected_peer_id="p1")
    assert maybe_build_attestation(
        env,
        peer_id="p1",
        response_text="ok",
        provider_mode="harness",
        llm_called=False,
    ) is None


def test_harness_attestation_8004_fields():
    env = PromptRequestEnvelope.visible_prompt(
        prompt="What is basalt?",
        selected_peer_id="expert_geo",
        proof_requirements=(PROOF_TLS_EXECUTION,),
        extra_intent={"agent_id": "42", "agent_registry": "eip155:8453:0xabc"},
    )
    text, att = expert_reply_with_attestation(env, "expert_geo")
    assert "[wire-harness expert_reply]" in text
    assert att is not None
    assert att["registry_profile"] == "eip-8004-validation-registry"
    req = att["validation_request"]
    resp = att["validation_response"]
    assert req["requestHash"] == resp["requestHash"]
    assert resp["tag"] == TAG_TENET_TLS_EXECUTION_V0
    assert resp["response"] == 100
    evidence = att["response_document"]["evidence"]
    assert evidence["evidence_family"] == "harness"
    assert evidence["claim"] == "runtime_execution"
    assert evidence["llm_called"] is False


def test_request_hash_stable_canonical_json():
    env = PromptRequestEnvelope.visible_prompt(
        prompt="x",
        selected_peer_id="p",
        proof_requirements=(PROOF_TLS_EXECUTION,),
        request_id="fixed-id",
    )
    a = build_execution_attestation(
        env, peer_id="p", response_text="y", provider_mode="harness", llm_called=False
    )
    b = build_execution_attestation(
        env, peer_id="p", response_text="y", provider_mode="harness", llm_called=False
    )
    assert a["validation_request"]["requestHash"] == b["validation_request"]["requestHash"]


def test_stream_done_payload_includes_attestation():
    att = {"validation_response": {"tag": TAG_TENET_TLS_EXECUTION_V0}}
    payload = stream_done_payload(3, attestation=att)
    assert payload["done"] is True
    assert payload["seq"] == 3
    assert payload["attestation"] == att


def test_envelope_roundtrip_proof_requirements():
    env = PromptRequestEnvelope.visible_prompt(
        prompt="q",
        selected_peer_id="p",
        proof_requirements=(PROOF_TLS_EXECUTION,),
    )
    restored = PromptRequestEnvelope.from_json(env.to_json())
    assert restored.proof_requirements == (PROOF_TLS_EXECUTION,)
    assert PROOF_NONE not in restored.proof_requirements or len(restored.proof_requirements) == 1
