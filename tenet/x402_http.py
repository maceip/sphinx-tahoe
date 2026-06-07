"""x402-over-HTTP: a 402-protected token endpoint settled on Algorand.

The server exposes ``GET /token?blinded=<hex>``:
  - with no ``X-PAYMENT`` header -> **HTTP 402** + PaymentRequirements JSON,
  - with a valid ``X-PAYMENT`` header (an Algorand payment proof) -> **HTTP 200**
    and a *blind signature* over the client's blinded token.

So a real on-chain Algorand payment unlocks a real unlinkable rate-limit token.
The verification reuses ``tenet.x402.verify_payment`` with a real algod
``tx_lookup``; nothing here is mocked.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tenet.blind_rsa import IssuerKey
from tenet.x402 import (
    PaymentPayload,
    PaymentRequirements,
    verify_payment,
)


class _State:
    def __init__(self):
        self.requirements: dict[str, PaymentRequirements] = {}
        self.seen_tx_ids: set[str] = set()
        self.lock = threading.Lock()

    def gc(self, now: float) -> None:
        self.requirements = {n: r for n, r in self.requirements.items() if r.expires_at > now}


def make_x402_handler(*, issuer: IssuerKey, pay_to: str, price_micro_algos: int, network: str, tx_lookup):
    state = _State()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet
            pass

        def _send_json(self, code: int, body: dict, extra_headers: dict | None = None):
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/token":
                self._send_json(404, {"error": "not found"})
                return
            qs = parse_qs(parsed.query)
            blinded_hex = (qs.get("blinded") or [""])[0]
            if not blinded_hex:
                self._send_json(400, {"error": "missing blinded token"})
                return

            payment_header = self.headers.get("X-PAYMENT")
            now = time.time()

            if not payment_header:
                # 402 Payment Required — issue the x402 challenge
                reqs = PaymentRequirements.create(
                    network=network, asset=0, amount=price_micro_algos, pay_to=pay_to,
                    resource="rate-limit-token", now=now,
                )
                with state.lock:
                    state.gc(now)
                    state.requirements[reqs.nonce] = reqs
                self._send_json(402, {"x402": reqs.to_dict()})
                return

            # Payment presented — verify it on-chain, then blind-sign
            try:
                payload = PaymentPayload.from_dict(
                    json.loads(base64.b64decode(payment_header).decode("utf-8"))
                )
            except Exception:
                self._send_json(400, {"error": "malformed X-PAYMENT"})
                return
            with state.lock:
                reqs = state.requirements.get(payload.nonce)
            if reqs is None:
                self._send_json(400, {"error": "unknown or expired payment nonce"})
                return
            verification = verify_payment(
                payload, reqs, tx_lookup=tx_lookup, seen_tx_ids=state.seen_tx_ids, now=now,
            )
            if not verification.ok:
                self._send_json(402, {"x402_error": verification.reason})
                return
            try:
                blinded = bytes.fromhex(blinded_hex)
                blind_sig = issuer.blind_sign(blinded)
            except Exception as exc:
                self._send_json(400, {"error": f"blind sign failed: {exc}"})
                return
            self._send_json(
                200,
                {"blind_sig": blind_sig.hex(), "payer": verification.payer},
                extra_headers={"X-PAYMENT-RESPONSE": base64.b64encode(
                    json.dumps({"settled": True, "tx_id": payload.tx_id}).encode()).decode()},
            )

    return Handler


def buy_token_over_x402(base_url: str, pub, pay_fn, *, timeout: float = 30.0):
    """Client: GET -> 402 -> pay (pay_fn) -> resubmit -> finalize a real token.

    ``pay_fn(requirements) -> tx_id`` performs the on-chain Algorand payment
    (real in the demo, a stub in tests). Returns (RateLimitToken, info_dict).
    """
    import urllib.request

    from tenet.rate_token import begin_token, complete_token

    req = begin_token(pub)
    blinded_hex = req.blinded_msg.hex()
    url = f"{base_url}/token?blinded={blinded_hex}"

    # 1. unpaid GET -> 402 with payment requirements
    try:
        urllib.request.urlopen(url, timeout=timeout)
        raise RuntimeError("expected HTTP 402, got 200")
    except urllib.error.HTTPError as exc:
        if exc.code != 402:
            raise
        reqs = PaymentRequirements.from_dict(json.loads(exc.read())["x402"])

    # 2. pay on Algorand
    tx_id = pay_fn(reqs)

    # 3. resubmit with the X-PAYMENT proof -> 200 + blind signature
    payload = PaymentPayload(
        network=reqs.network, asset=reqs.asset, amount=reqs.amount,
        payer="", tx_id=tx_id, nonce=reqs.nonce,
    )
    header = base64.b64encode(json.dumps(payload.to_dict()).encode()).decode()
    paid_req = urllib.request.Request(url, headers={"X-PAYMENT": header})
    with urllib.request.urlopen(paid_req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    blind_sig = bytes.fromhex(body["blind_sig"])
    token = complete_token(pub, req, blind_sig)
    return token, {"tx_id": tx_id, "payer": body.get("payer"), "requirements": reqs}


class X402Server:
    """Threaded x402 token server (real HTTP 402)."""

    def __init__(self, *, issuer: IssuerKey, pay_to: str, price_micro_algos: int, network: str, tx_lookup, host="127.0.0.1", port=0):
        handler = make_x402_handler(
            issuer=issuer, pay_to=pay_to, price_micro_algos=price_micro_algos,
            network=network, tx_lookup=tx_lookup,
        )
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self.port = self._httpd.server_address[1]
        self.host = host
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
