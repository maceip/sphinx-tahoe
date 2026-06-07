"""x402 payment handshake for token issuance, settled on Algorand.

x402 (HTTP 402 Payment Required) flow for buying rate-limit tokens:

  1. client requests issuance -> issuer replies 402 with PaymentRequirements
     (amount, asset, pay-to, network, nonce, expiry).
  2. client pays on Algorand (a USDC/ALGO transfer to pay-to) and resubmits with
     a PaymentPayload carrying the Algorand txid.
  3. issuer verifies the on-chain payment matches the requirements, then
     blind-signs the token (see tenet.rate_token.issue_blind_sig).

This module is the *verification* side: it is fully real and testable. The two
deployment inputs are injected, not faked in the logic:
  - ``tx_lookup``: an algod-backed callable that returns the confirmed on-chain
    transaction details for a txid (None if not found/unconfirmed).
  - the client's funded-account signature that produced the Algorand transfer.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable

# Algorand mainnet USDC ASA id (asset 0 / "ALGO" = native token).
USDC_ASA_MAINNET = 31566704

X402_SCHEME = "exact"  # x402 "exact amount" scheme


@dataclass(frozen=True)
class PaymentRequirements:
    """The 402 challenge body: what the client must pay."""

    network: str            # e.g. "algorand-mainnet"
    asset: int              # ASA id (0 = native ALGO)
    amount: int             # minimum amount required, in the asset's base units
    pay_to: str             # Algorand address that must receive the payment
    resource: str           # what is being bought, e.g. "tokens:soup.expert~tenet"
    nonce: str
    expires_at: float
    scheme: str = X402_SCHEME

    @classmethod
    def create(
        cls,
        *,
        network: str,
        asset: int,
        amount: int,
        pay_to: str,
        resource: str,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> "PaymentRequirements":
        issued = time.time() if now is None else now
        return cls(
            network=network, asset=int(asset), amount=int(amount), pay_to=pay_to,
            resource=resource, nonce=os.urandom(16).hex(), expires_at=issued + ttl_seconds,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "scheme": self.scheme, "network": self.network, "asset": self.asset,
            "amount": self.amount, "pay_to": self.pay_to, "resource": self.resource,
            "nonce": self.nonce, "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "PaymentRequirements":
        return cls(
            network=str(raw["network"]), asset=int(raw["asset"]), amount=int(raw["amount"]),
            pay_to=str(raw["pay_to"]), resource=str(raw["resource"]), nonce=str(raw["nonce"]),
            expires_at=float(raw["expires_at"]), scheme=str(raw.get("scheme", X402_SCHEME)),
        )


@dataclass(frozen=True)
class PaymentPayload:
    """The X-PAYMENT header: proof the client paid (an Algorand txid)."""

    network: str
    asset: int
    amount: int
    payer: str       # Algorand address that paid
    tx_id: str       # Algorand transaction id
    nonce: str       # echoes the requirements nonce
    scheme: str = X402_SCHEME

    def to_dict(self) -> dict[str, object]:
        return {
            "scheme": self.scheme, "network": self.network, "asset": self.asset,
            "amount": self.amount, "payer": self.payer, "tx_id": self.tx_id, "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "PaymentPayload":
        return cls(
            network=str(raw["network"]), asset=int(raw["asset"]), amount=int(raw["amount"]),
            payer=str(raw["payer"]), tx_id=str(raw["tx_id"]), nonce=str(raw["nonce"]),
            scheme=str(raw.get("scheme", X402_SCHEME)),
        )


@dataclass(frozen=True)
class ConfirmedTx:
    """What an algod tx-lookup returns for a confirmed transaction."""

    sender: str
    receiver: str
    amount: int
    asset: int           # 0 = native ALGO, else ASA id
    confirmed_round: int


# tx_lookup(tx_id) -> ConfirmedTx | None  (algod-backed in prod, fake in tests)
TxLookup = Callable[[str], "ConfirmedTx | None"]


@dataclass(frozen=True)
class PaymentVerification:
    ok: bool
    reason: str | None = None
    payer: str | None = None


def verify_payment(
    payload: PaymentPayload,
    requirements: PaymentRequirements,
    *,
    tx_lookup: TxLookup,
    seen_tx_ids: set | None = None,
    now: float | None = None,
) -> PaymentVerification:
    """Verify an x402 payment against the requirements and the Algorand chain.

    Checks (all must hold, else fail closed):
      * the requirements have not expired and the nonce matches,
      * scheme/network/asset match,
      * the on-chain tx (via ``tx_lookup``) is confirmed and pays >= amount to
        pay_to in the right asset,
      * the txid has not already been used to fund another issuance (replay).
    """

    ts = time.time() if now is None else now
    if ts >= requirements.expires_at:
        return PaymentVerification(False, "requirements_expired")
    if payload.nonce != requirements.nonce:
        return PaymentVerification(False, "nonce_mismatch")
    if payload.scheme != requirements.scheme:
        return PaymentVerification(False, "scheme_mismatch")
    if payload.network != requirements.network:
        return PaymentVerification(False, "network_mismatch")
    if payload.asset != requirements.asset:
        return PaymentVerification(False, "asset_mismatch")

    if seen_tx_ids is not None and payload.tx_id in seen_tx_ids:
        return PaymentVerification(False, "tx_replay")

    tx = tx_lookup(payload.tx_id)
    if tx is None:
        return PaymentVerification(False, "tx_not_found_or_unconfirmed")
    if tx.confirmed_round <= 0:
        return PaymentVerification(False, "tx_unconfirmed")
    if tx.receiver != requirements.pay_to:
        return PaymentVerification(False, "wrong_receiver")
    if tx.asset != requirements.asset:
        return PaymentVerification(False, "wrong_asset_on_chain")
    if tx.amount < requirements.amount:
        return PaymentVerification(False, "underpaid")

    if seen_tx_ids is not None:
        seen_tx_ids.add(payload.tx_id)
    return PaymentVerification(True, payer=tx.sender)
