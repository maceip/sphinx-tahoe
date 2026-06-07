"""x402-EURD-gated Expert Pick endpoint test (real HTTP, stub experts/payment)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from tenet.pick_server import PickServer
from tenet.quantoz import EURD_ASA_MAINNET, build_bridge_proof

PAY_TO = "ALGO_MERCHANT_WHITELISTED"
PRICE = 50  # €0.50 in EURD atomic units (2 decimals)

QUESTION = "Which laptop for ML dev?"
OPTIONS = [
    {"id": "mbp", "label": "MacBook Pro M3"},
    {"id": "tp", "label": "ThinkPad"},
    {"id": "fw", "label": "Framework"},
]


def _expert(pick):
    payload = json.dumps({"pick": pick, "ranking": [pick], "reasoning": "merit", "confidence": 0.9, "disclosures": ["none"]})
    return lambda _prompt: payload


def _server(verify=lambda _p: (True, "AGENT_X"), weight_fn=None):
    experts = [("e1", _expert("mbp")), ("e2", _expert("mbp")), ("e3", _expert("tp"))]
    srv = PickServer(
        experts=experts, pay_to=PAY_TO, price_eurd_atomic=PRICE,
        verify_payment=verify, weight_fn=weight_fn, asset=EURD_ASA_MAINNET,
    )
    srv.start()
    return srv


def _post(url, body, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    return urllib.request.urlopen(req, timeout=5)


def test_unpaid_pick_returns_402_with_eurd_requirements():
    srv = _server()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(f"{srv.base_url}/pick", {"question": QUESTION, "options": OPTIONS})
        assert exc.value.code == 402
        body = json.loads(exc.value.read())
        accept = body["accepts"][0]
        assert accept["scheme"] == "exact"
        assert accept["network"] == "algorand:mainnet"
        assert accept["asset"] == str(EURD_ASA_MAINNET)
        assert accept["payTo"] == PAY_TO
        assert accept["maxAmountRequired"] == str(PRICE)
    finally:
        srv.stop()


def test_paid_pick_runs_consensus():
    srv = _server()
    try:
        proof = build_bridge_proof(asset=EURD_ASA_MAINNET, pay_to=PAY_TO, transaction_code="QP_DEMO_1")
        resp = _post(f"{srv.base_url}/pick", {"question": QUESTION, "options": OPTIONS}, {"X-PAYMENT": proof})
        body = json.loads(resp.read())
        assert body["pick_id"] == "mbp"           # 2 of 3 experts -> consensus
        assert body["agreement"] == pytest.approx(2 / 3)
        assert body["payer"] == "AGENT_X"
        assert body["tx"] == "QP_DEMO_1"
        assert set(body["ranking"]) == {"mbp", "tp", "fw"}
    finally:
        srv.stop()


def test_reputation_weight_excludes_flagged_expert():
    # e3 (the dissenter) is heavily weighted but flagged -> excluded; consensus unchanged
    srv = _server(weight_fn=lambda e: 0.0 if e == "e3" else 1.0)
    try:
        proof = build_bridge_proof(asset=EURD_ASA_MAINNET, pay_to=PAY_TO, transaction_code="QP_DEMO_2")
        resp = _post(f"{srv.base_url}/pick", {"question": QUESTION, "options": OPTIONS}, {"X-PAYMENT": proof})
        body = json.loads(resp.read())
        assert body["pick_id"] == "mbp"
        assert "e3" in body["excluded_experts"]
        assert body["agreement"] == pytest.approx(1.0)  # only e1,e2 count, both "mbp"
    finally:
        srv.stop()


def test_unverified_payment_rejected():
    srv = _server(verify=lambda _p: (False, None))
    try:
        proof = build_bridge_proof(asset=EURD_ASA_MAINNET, pay_to=PAY_TO, transaction_code="BAD")
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(f"{srv.base_url}/pick", {"question": QUESTION, "options": OPTIONS}, {"X-PAYMENT": proof})
        assert exc.value.code == 402
        assert json.loads(exc.value.read())["x402_error"] == "payment not verified"
    finally:
        srv.stop()


def test_malformed_payment_rejected():
    srv = _server()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(f"{srv.base_url}/pick", {"question": QUESTION, "options": OPTIONS}, {"X-PAYMENT": "not-base64-proof"})
        assert exc.value.code == 400
    finally:
        srv.stop()
