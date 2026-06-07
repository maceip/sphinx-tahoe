"""x402-over-HTTP flow test: real HTTP 402, blind-token issuance, fake chain.

Validates the full plumbing (402 challenge -> X-PAYMENT -> blind signature ->
finalized token) deterministically. The only thing not exercised here is the live
Algorand payment itself (a stub tx_lookup stands in).
"""

from __future__ import annotations

import pytest

from tenet.blind_rsa import IssuerKey
from tenet.rate_token import NullifierLedger, spend_token
from tenet.x402 import ConfirmedTx
from tenet.x402_http import X402Server, buy_token_over_x402

PAY_TO = "ALGO_POOL_PAYTO"
PRICE = 1_000_000  # 1 testnet ALGO in microAlgos


@pytest.fixture(scope="module")
def issuer():
    return IssuerKey.generate(bits=2048)


def _server(issuer, tx_lookup):
    srv = X402Server(
        issuer=issuer, pay_to=PAY_TO, price_micro_algos=PRICE,
        network="algorand-testnet", tx_lookup=tx_lookup,
    )
    srv.start()
    return srv


def test_pay_unlocks_a_real_token(issuer):
    # fake chain: any txid is a confirmed payment of the right amount to PAY_TO
    tx_lookup = lambda _id: ConfirmedTx("ALICE", PAY_TO, PRICE, 0, 100)
    srv = _server(issuer, tx_lookup)
    try:
        token, info = buy_token_over_x402(
            srv.base_url, issuer.public, pay_fn=lambda reqs: "FAKE_TX_1",
        )
        # the returned token is a real, spendable blind-signed token
        ledger = NullifierLedger()
        nf = spend_token(issuer.public, token, ledger)
        assert ledger.is_spent(nf)
        assert info["tx_id"] == "FAKE_TX_1"
    finally:
        srv.stop()


def test_unpaid_request_gets_402(issuer):
    import urllib.error
    import urllib.request

    srv = _server(issuer, lambda _id: None)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{srv.base_url}/token?blinded=ab", timeout=5)
        assert exc.value.code == 402
        import json

        body = json.loads(exc.value.read())
        assert body["x402"]["pay_to"] == PAY_TO
        assert body["x402"]["amount"] == PRICE
    finally:
        srv.stop()


def test_underpaid_payment_is_rejected(issuer):
    # chain says the payment was too small
    tx_lookup = lambda _id: ConfirmedTx("ALICE", PAY_TO, 1, 0, 100)
    srv = _server(issuer, tx_lookup)
    try:
        with pytest.raises(Exception):  # buy raises on non-200 resubmit
            buy_token_over_x402(srv.base_url, issuer.public, pay_fn=lambda reqs: "FAKE_TX_2")
    finally:
        srv.stop()
