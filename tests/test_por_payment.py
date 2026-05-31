import json

from por.envelope import PromptRequestEnvelope
from por.payment import (
    SCHEME_ZKTLS_CONDITIONAL,
    build_payment_terms,
    payment_terms_from_envelope,
    request_binding_hash,
    stream_done_payload,
)
from por.provider import PayInRequiredError, expert_reply_with_settlement


def _envelope_with_payment(*, verified: bool = True) -> PromptRequestEnvelope:
    env = PromptRequestEnvelope.visible_prompt(
        prompt="Explain basalt",
        selected_peer_id="expert_geo",
        requested_expertise="geology",
    )
    terms = build_payment_terms(
        env,
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


def test_harness_expert_reply_with_settlement():
    env = _envelope_with_payment()
    text, settlement = expert_reply_with_settlement(env, "expert_geo")
    assert "[wire-harness expert_reply]" in text
    assert settlement is not None
    assert settlement["status"] == "proof_due"
    assert settlement["pay_in"]["verified"] is True
    assert settlement["payout"]["status"] == "payout_pending"


def test_pay_in_strict_rejects_unverified(monkeypatch):
    monkeypatch.setenv("POR_PAYMENT_VERIFY", "strict")
    env = _envelope_with_payment(verified=False)
    try:
        expert_reply_with_settlement(env, "expert_geo")
    except PayInRequiredError:
        pass
    else:
        raise AssertionError("expected PayInRequiredError")


def test_stream_done_payload_settlement():
    payload = stream_done_payload(2, settlement={"status": "proof_due"})
    assert payload["done"] is True
    assert payload["payment_settlement"]["status"] == "proof_due"


def test_envelope_roundtrip_payment_terms():
    env = _envelope_with_payment()
    restored = PromptRequestEnvelope.from_json(env.to_json())
    assert restored.payment_terms is not None
    assert restored.payment_terms["scheme"] == SCHEME_ZKTLS_CONDITIONAL
