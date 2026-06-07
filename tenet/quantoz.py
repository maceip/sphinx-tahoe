"""Quantoz EURD x402 adapter (MiCA-compliant euro stablecoin on Algorand).

Python port of @ever_amsterdam/x402-euro-eurd (author: Quantoz). Lets our x402
merchant accept EURD payments and lets an agent pay them, two ways:

  - "euro"  : off-chain Quantoz managed-account transfer (instant).
  - "exact" on algorand:mainnet : the EURO->Algorand bridge — Quantoz converts the
    agent's EURO balance to EURD and settles on-chain to the merchant's Algorand
    address. The merchant needs only a whitelisted Algorand address.

Live payment needs Quantoz credentials (QUANTOZ_API_KEY + a funded ACC_xxxxx).
The 402/accepts/proof encoding is offline + testable; the payment hits the
Quantoz API.
"""

from __future__ import annotations

import base64
import json
import urllib.request
from dataclasses import dataclass

QUANTOZ_BASE_URL = "https://api.quantozpay.com"
EURD_ASA_MAINNET = 1221682136
ALGORAND_MAINNET = "algorand:mainnet"


class QuantozError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# base64url (matches Node Buffer.toString("base64url"): urlsafe, no padding)
# --------------------------------------------------------------------------- #


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --------------------------------------------------------------------------- #
# 402 accepts (merchant side)
# --------------------------------------------------------------------------- #


def bridge_accept(
    *,
    pay_to: str,
    max_amount_required: int | str,
    asset: int = EURD_ASA_MAINNET,
    resource: str | None = None,
    facilitator: str | None = None,
    max_timeout_seconds: int | None = None,
) -> dict:
    """Build an Algorand-bridge `accepts` entry for a 402 response.

    ``max_amount_required`` is in atomic units (EURD has 2 decimals: 10 = €0.10).
    """
    a: dict = {
        "scheme": "exact",
        "network": ALGORAND_MAINNET,
        "asset": str(asset),
        "maxAmountRequired": str(max_amount_required),
        "payTo": pay_to,
    }
    if resource is not None:
        a["resource"] = resource
    if facilitator is not None:
        a["facilitator"] = facilitator
    if max_timeout_seconds is not None:
        a["maxTimeoutSeconds"] = max_timeout_seconds
    return a


def x402_402_body(accepts: list[dict]) -> dict:
    return {"x402Version": 2, "accepts": accepts}


# --------------------------------------------------------------------------- #
# X-PAYMENT proof (agent side / merchant parse)
# --------------------------------------------------------------------------- #


def build_bridge_proof(*, asset: int | str, pay_to: str, transaction_code: str, network: str = ALGORAND_MAINNET) -> str:
    proof = {
        "x402Version": 2,
        "scheme": "exact",
        "network": network,
        "payload": {"transactionCode": transaction_code, "payTo": pay_to, "asset": str(asset)},
    }
    return _b64url(json.dumps(proof).encode("utf-8"))


@dataclass(frozen=True)
class BridgeProof:
    network: str
    transaction_code: str
    pay_to: str
    asset: str


def parse_bridge_proof(x_payment: str) -> BridgeProof | None:
    try:
        decoded = json.loads(_b64url_decode(x_payment).decode("utf-8"))
    except Exception:
        return None
    if decoded.get("scheme") != "exact":
        return None
    payload = decoded.get("payload") or {}
    if not payload.get("transactionCode"):
        return None
    return BridgeProof(
        network=str(decoded.get("network", "")),
        transaction_code=str(payload["transactionCode"]),
        pay_to=str(payload.get("payTo", "")),
        asset=str(payload.get("asset", "")),
    )


# --------------------------------------------------------------------------- #
# Quantoz payment API (agent side; needs credentials)
# --------------------------------------------------------------------------- #


def _post(url: str, api_key: str, body: dict, *, timeout: float = 30.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, (json.loads(text) if text else {})
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        raise QuantozError(_parse_api_error(exc.code, text)) from exc


def pay_algorand_bridge(
    *,
    api_key: str,
    from_account: str,
    pay_to: str,
    amount_eur: float,
    base_url: str = QUANTOZ_BASE_URL,
) -> str:
    """Pay an Algorand address via the Quantoz EURO->EURD bridge. Returns the
    Quantoz ``transactionCode`` used as the x402 proof."""
    _status, body = _post(
        f"{base_url.rstrip('/')}/transaction/payment", api_key,
        {
            "paymentFrom": from_account, "paymentTo": pay_to, "toType": "BlockchainAddress",
            "amount": amount_eur, "shareName": False, "message": "x402 bridge payment",
        },
    )
    code = body.get("transactionCode") or (body.get("value") or {}).get("transactionCode")
    if not code:
        raise QuantozError("bridge payment succeeded but no transactionCode returned")
    return str(code)


def pay_payment_request(
    *,
    api_key: str,
    from_account: str,
    payment_request_code: str,
    amount_eur: float,
    base_url: str = QUANTOZ_BASE_URL,
) -> None:
    """Pay a Quantoz payment request (off-chain euro scheme)."""
    _post(
        f"{base_url.rstrip('/')}/transaction/payment", api_key,
        {
            "paymentFrom": from_account, "paymentTo": payment_request_code,
            "toType": "PaymentRequestCode", "amount": amount_eur,
            "shareName": False, "message": "x402 payment",
        },
    )


def make_settlement_verifier(idx, *, pay_to: str, min_atomic: int, asset: int = EURD_ASA_MAINNET, seen: set | None = None):
    """Real merchant-side verification: confirm the EURD actually landed on-chain.

    Quantoz settles EURD to ``pay_to`` asynchronously, so the merchant watches its
    own address (via an algosdk IndexerClient) for an incoming EURD asset transfer
    of at least ``min_atomic`` units, and burns the settlement txid so one payment
    can't be replayed across requests. Returns a ``verify_payment(proof)`` callable
    matching the PickServer / x402 contract.
    """
    spent = seen if seen is not None else set()

    def verify(_proof) -> tuple:
        try:
            res = idx.search_transactions(
                address=pay_to, address_role="receiver", asset_id=asset, limit=50,
            )
        except Exception:
            return (False, None)
        for tx in res.get("transactions", []) or []:
            txid = tx.get("id")
            if txid in spent:
                continue
            ax = tx.get("asset-transfer-transaction", {}) or {}
            if ax.get("receiver") == pay_to and int(ax.get("amount", 0) or 0) >= min_atomic:
                spent.add(txid)
                return (True, tx.get("sender"))
        return (False, None)

    return verify


def _parse_api_error(status: int, text: str) -> str:
    try:
        j = json.loads(text)
        errs = j.get("errors")
        if errs:
            return "; ".join(e.get("message", "") for e in errs)
        if j.get("title"):
            return str(j["title"])
    except Exception:
        if text:
            return text
    return f"Quantoz payment failed ({status})"
