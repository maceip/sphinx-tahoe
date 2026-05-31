from por.envelope import PromptRequestEnvelope
from por.execution import UPSTREAM_PROFILES, build_execution_trace
from por.payment import (
    SCHEME_ERC8004_STAKE,
    SCHEME_SPONSORED_SERVICE,
    SCHEME_ZKTLS_CONDITIONAL,
    build_default_tenet_payment_terms,
    build_erc8004_stake_terms,
    build_payment_terms,
    build_sponsored_service_terms,
    payment_terms_from_envelope,
    request_binding_hash,
    stream_done_payload,
)
from por.provider import PayInRequiredError, expert_reply_with_settlement
from por.settlement import stream_done_with_verification


def _envelope_with_payment(*, verified: bool = True) -> PromptRequestEnvelope:
    env = PromptRequestEnvelope.visible_prompt(
        prompt="Explain basalt",
        selected_peer_id="expert_geo",
        requested_expertise="geology",
    )
    terms = build_payment_terms(
        env,
        scheme=SCHEME_ZKTLS_CONDITIONAL,
        pay_in={"ref": "escrow:demo", "amount": "1000", "asset": "USDC", "verified": verified},
        payout={"payee": "expert_geo", "amount": "1000", "asset": "USDC"},
        release={
            "predicate": "tls_upstream_response",
            "allowed_hosts": ["api.anthropic.com", "api.openai.com"],
        },
    )
    return PromptRequestEnvelope.visible_prompt(
        prompt="Explain basalt",
        selected_peer_id="expert_geo",
        requested_expertise="geology",
        request_id=env.request_id,
        payment_terms=terms,
    )


def test_request_binding_stable():
    env = PromptRequestEnvelope.visible_prompt("x", selected_peer_id="p")
    assert request_binding_hash(env) == request_binding_hash(env)


def test_payment_terms_validate_binding():
    env = _envelope_with_payment()
    terms = payment_terms_from_envelope(env)
    assert terms is not None
    assert terms.scheme == SCHEME_ZKTLS_CONDITIONAL


def test_sponsored_service_terms():
    env = PromptRequestEnvelope.visible_prompt("hi", selected_peer_id="expert_1")
    terms = build_sponsored_service_terms(env, sponsor_id="tenet-network")
    assert terms["scheme"] == SCHEME_SPONSORED_SERVICE
    sponsor = terms["pay_in"]["sponsor"]
    assert "gas" in sponsor["covers"]
    assert "expert_fee" in sponsor["covers"]


def test_erc8004_stake_terms():
    env = PromptRequestEnvelope.visible_prompt("hi", selected_peer_id="expert_1")
    terms = build_erc8004_stake_terms(
        env,
        agent_registry="eip155:8453:0xabc",
        agent_id="7",
        stake_wei="1000000000000000000",
    )
    assert terms["scheme"] == SCHEME_ERC8004_STAKE
    assert terms["pay_in"]["stake"]["stake_sufficient"] is True


def test_default_tenet_prefers_stake():
    env = PromptRequestEnvelope.visible_prompt(
        "hi",
        selected_peer_id="expert_1",
        extra_intent={
            "agent_registry": "eip155:8453:0xabc",
            "agent_id": "1",
            "stake_wei": "99",
        },
    )
    terms = build_default_tenet_payment_terms(env)
    assert terms["scheme"] == SCHEME_ERC8004_STAKE


def test_default_tenet_sponsored_without_agent():
    env = PromptRequestEnvelope.visible_prompt("hi", selected_peer_id="expert_1")
    terms = build_default_tenet_payment_terms(env)
    assert terms["scheme"] == SCHEME_SPONSORED_SERVICE


def test_execution_trace_two_hosts():
    assert set(UPSTREAM_PROFILES) == {"anthropic", "openai"}
    env = PromptRequestEnvelope.visible_prompt("q", selected_peer_id="p")
    trace = build_execution_trace(env, peer_id="p", provider_mode="anthropic", response_text="a")
    assert trace["proof_obligation"]["upstream_host"] == "api.anthropic.com"
    assert trace["steps"][0]["proof_system"] == "dx_dctls_export.v0"


def test_harness_expert_reply_with_settlement():
    env = _envelope_with_payment()
    text, completion = expert_reply_with_settlement(env, "expert_geo")
    assert "[wire-harness expert_reply]" in text
    assert completion is not None
    assert "execution_trace" in completion
    settlement = completion["payment_settlement"]
    assert settlement["status"] == "proof_due"
    assert settlement["pay_in"]["verified"] is True
    assert settlement["payout"]["status"] == "payout_pending"
    assert completion["execution_trace"]["proof_obligation"]["status"] == "harness_stub"


def test_pay_in_strict_rejects_unverified_stake(monkeypatch):
    monkeypatch.setenv("POR_PAYMENT_VERIFY", "strict")
    base = PromptRequestEnvelope.visible_prompt("hi", selected_peer_id="expert_1")
    env = PromptRequestEnvelope.visible_prompt(
        "hi",
        selected_peer_id="expert_1",
        request_id=base.request_id,
        payment_terms=build_erc8004_stake_terms(
            base,
            agent_registry="eip155:1:0x1",
            agent_id="1",
            stake_wei="1",
            stake_sufficient=False,
        ),
    )
    try:
        expert_reply_with_settlement(env, "expert_1")
    except PayInRequiredError:
        pass
    else:
        raise AssertionError("expected PayInRequiredError")


def test_stream_done_with_verification():
    payload = stream_done_with_verification(
        2,
        completion={
            "execution_trace": {"type": "por.execution_trace.v0"},
            "payment_settlement": {"status": "proof_due"},
        },
    )
    assert payload["done"] is True
    assert payload["execution_trace"]["type"] == "por.execution_trace.v0"
    assert payload["payment_settlement"]["status"] == "proof_due"


def test_envelope_roundtrip_payment_terms():
    env = _envelope_with_payment()
    restored = PromptRequestEnvelope.from_json(env.to_json())
    assert restored.payment_terms is not None
    assert restored.payment_terms["scheme"] == SCHEME_ZKTLS_CONDITIONAL
