#!/usr/bin/env python3
"""Runnable Expert Pick demo: x402-402 -> EURD pay -> reputation-weighted consensus.

Real LLM experts if ANTHROPIC_API_KEY is set, else deterministic stub experts.
Payment is stubbed (live EURD needs Quantoz creds); the HTTP 402 -> X-PAYMENT ->
consensus flow is real. Run: python3 scripts/expert_pick_demo.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenet.expert_pick import anthropic_llm
from tenet.pick_server import PickServer
from tenet.quantoz import EURD_ASA_MAINNET, build_bridge_proof

PAY_TO = "MERCHANT_WHITELISTED_ALGO_ADDR"
PRICE = 50  # €0.50 EURD atomic units

QUESTION = "Which laptop should I buy for local ML development on a budget?"
OPTIONS = [
    {"id": "mbp", "label": "MacBook Pro M3", "detail": "32GB unified, great battery, pricey"},
    {"id": "tp", "label": "ThinkPad P1", "detail": "RTX GPU, Linux-friendly, heavier"},
    {"id": "fw", "label": "Framework 16", "detail": "repairable, modular GPU, newer"},
]


def _stub_expert(pick, reason):
    payload = json.dumps({"pick": pick, "ranking": [pick], "reasoning": reason,
                          "confidence": 0.85, "disclosures": ["none"]})
    return lambda _prompt: payload


def main() -> int:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        llm = anthropic_llm(key)
        experts = [(f"expert-{i}", llm) for i in range(3)]
        print("experts: 3x live Claude")
    else:
        experts = [
            ("e-hardware", _stub_expert("fw", "modular GPU + repairability win for budget ML")),
            ("e-ml", _stub_expert("tp", "discrete RTX GPU matters most for local training")),
            ("e-value", _stub_expert("fw", "best price/longevity")),
        ]
        print("experts: 3x stub (set ANTHROPIC_API_KEY for live)")

    # reputation: e-ml is flagged (recent bad picks) -> excluded from consensus
    weight_fn = lambda e: 0.0 if e == "e-ml" else 1.0

    srv = PickServer(
        experts=experts, pay_to=PAY_TO, price_eurd_atomic=PRICE,
        verify_payment=lambda _proof: (True, "AGENT_BUYER"),  # live: quantoz.make_settlement_verifier
        weight_fn=weight_fn, asset=EURD_ASA_MAINNET,
    )
    srv.start()
    url = f"{srv.base_url}/pick"
    print(f"server: {url}\n")

    def post(headers=None):
        req = urllib.request.Request(
            url, data=json.dumps({"question": QUESTION, "options": OPTIONS}).encode(),
            method="POST", headers={"Content-Type": "application/json", **(headers or {})},
        )
        return urllib.request.urlopen(req, timeout=90)

    try:
        # 1. unpaid -> 402
        try:
            post()
        except urllib.error.HTTPError as exc:
            assert exc.code == 402
            accept = json.loads(exc.read())["accepts"][0]
            print(f"[402] pay {int(accept['maxAmountRequired'])/100:.2f} EURD (asset {accept['asset']}) "
                  f"to {accept['payTo']} on {accept['network']}")

        # 2. pay EURD (stub) -> X-PAYMENT proof
        proof = build_bridge_proof(asset=EURD_ASA_MAINNET, pay_to=PAY_TO, transaction_code="QP_DEMO")
        print("[pay] EURD settled, txCode=QP_DEMO -> resubmitting with X-PAYMENT")

        # 3. paid -> consensus pick
        body = json.loads(post({"X-PAYMENT": proof}).read())
        print("\n=== EXPERT PICK (reputation-weighted consensus) ===")
        print(f"  pick:      {body['pick_id']}")
        print(f"  ranking:   {' > '.join(body['ranking'])}")
        print(f"  agreement: {body['agreement']:.0%}")
        print(f"  experts:   {body['contributing_experts']}  excluded(flagged): {body['excluded_experts']}")
        print(f"  paid by:   {body['payer']}  tx: {body['tx']}")
        return 0
    finally:
        srv.stop()


if __name__ == "__main__":
    raise SystemExit(main())
