"""x402-EURD-gated Expert Pick endpoint (the tenet product surface).

  POST /pick  {question, options:[{id,label,detail}], context?}
    - no X-PAYMENT  -> HTTP 402 + Quantoz EURD payment requirements
    - valid X-PAYMENT (an EURD bridge proof) -> run reputation-weighted multi-
      expert consensus and return the pick.

So an agent (or human) pays EURD on Algorand via x402 and gets a trustworthy,
gaming-resistant recommendation instead of an SEO-ranked guess. Payment
verification and the expert LLMs are injected; nothing here is mocked in shape.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from tenet.expert_pick import LLM, Option, consensus, recommend
from tenet.quantoz import bridge_accept, parse_bridge_proof, x402_402_body

# verify_payment(BridgeProof) -> (ok: bool, payer: str | None)
VerifyPayment = Callable[[object], tuple]


def make_pick_handler(
    *,
    experts: list[tuple[str, LLM]],
    pay_to: str,
    price_eurd_atomic: int,
    verify_payment: VerifyPayment,
    weight_fn: Callable[[str], float] | None = None,
    asset: int | None = None,
):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _json(self, code: int, body: dict, headers: dict | None = None):
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path.split("?")[0] != "/pick":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                question = str(body["question"])
                options = [Option(id=str(o["id"]), label=str(o.get("label", o["id"])),
                                  detail=str(o.get("detail", ""))) for o in body["options"]]
                context = body.get("context")
            except Exception as exc:
                self._json(400, {"error": f"bad request: {exc}"})
                return
            if len(options) < 2:
                self._json(400, {"error": "need at least two options"})
                return

            accept_kwargs = {"pay_to": pay_to, "max_amount_required": price_eurd_atomic,
                             "resource": "expert-pick"}
            if asset is not None:
                accept_kwargs["asset"] = asset

            payment_header = self.headers.get("X-PAYMENT")
            if not payment_header:
                self._json(402, x402_402_body([bridge_accept(**accept_kwargs)]))
                return

            proof = parse_bridge_proof(payment_header)
            if proof is None:
                self._json(400, {"error": "malformed X-PAYMENT proof"})
                return
            ok, payer = verify_payment(proof)
            if not ok:
                self._json(402, {"x402_error": "payment not verified"})
                return

            # paid: run the reputation-weighted multi-expert consensus
            picks = []
            for expert_id, llm in experts:
                try:
                    picks.append(recommend(question, options, llm=llm, expert_id=expert_id, context=context))
                except Exception:
                    continue  # a flaky expert doesn't sink the quorum
            if not picks:
                self._json(502, {"error": "no expert produced a valid pick"})
                return
            result = consensus(picks, options, weight_fn=weight_fn)
            out = result.to_dict()
            out["payer"] = payer
            out["tx"] = proof.transaction_code
            self._json(200, out)

    return Handler


class PickServer:
    def __init__(
        self,
        *,
        experts: list[tuple[str, LLM]],
        pay_to: str,
        price_eurd_atomic: int,
        verify_payment: VerifyPayment,
        weight_fn: Callable[[str], float] | None = None,
        asset: int | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        handler = make_pick_handler(
            experts=experts, pay_to=pay_to, price_eurd_atomic=price_eurd_atomic,
            verify_payment=verify_payment, weight_fn=weight_fn, asset=asset,
        )
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self.host, self.port = host, self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
