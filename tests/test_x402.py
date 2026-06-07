"""Tests for the x402 payment handshake + Algorand verification."""

from __future__ import annotations

from tenet.x402 import (
    USDC_ASA_MAINNET,
    ConfirmedTx,
    PaymentPayload,
    PaymentRequirements,
    verify_payment,
)

NET = "algorand-mainnet"
PAY_TO = "ALGO_POOL_PAYTO_ADDR"


def _reqs(now=1000.0, amount=1_000_000):
    return PaymentRequirements.create(
        network=NET, asset=USDC_ASA_MAINNET, amount=amount, pay_to=PAY_TO,
        resource="tokens:soup.expert~tenet", now=now,
    )


def _payload(reqs, *, amount=1_000_000, tx_id="TX1", payer="ALICE"):
    return PaymentPayload(
        network=reqs.network, asset=reqs.asset, amount=amount, payer=payer,
        tx_id=tx_id, nonce=reqs.nonce,
    )


def _lookup(tx: ConfirmedTx | None):
    return lambda _tx_id: tx


def test_valid_payment_verifies():
    reqs = _reqs()
    payload = _payload(reqs)
    tx = ConfirmedTx(sender="ALICE", receiver=PAY_TO, amount=1_000_000, asset=USDC_ASA_MAINNET, confirmed_round=42)
    v = verify_payment(payload, reqs, tx_lookup=_lookup(tx), now=1100.0)
    assert v.ok and v.payer == "ALICE"


def test_overpayment_ok_underpayment_rejected():
    reqs = _reqs(amount=1_000_000)
    tx_over = ConfirmedTx("ALICE", PAY_TO, 2_000_000, USDC_ASA_MAINNET, 42)
    assert verify_payment(_payload(reqs, amount=2_000_000), reqs, tx_lookup=_lookup(tx_over), now=1100.0).ok
    tx_under = ConfirmedTx("ALICE", PAY_TO, 500_000, USDC_ASA_MAINNET, 42)
    v = verify_payment(_payload(reqs), reqs, tx_lookup=_lookup(tx_under), now=1100.0)
    assert not v.ok and v.reason == "underpaid"


def test_wrong_receiver_rejected():
    reqs = _reqs()
    tx = ConfirmedTx("ALICE", "SOMEONE_ELSE", 1_000_000, USDC_ASA_MAINNET, 42)
    v = verify_payment(_payload(reqs), reqs, tx_lookup=_lookup(tx), now=1100.0)
    assert not v.ok and v.reason == "wrong_receiver"


def test_wrong_asset_rejected():
    reqs = _reqs()
    tx = ConfirmedTx("ALICE", PAY_TO, 1_000_000, asset=0, confirmed_round=42)  # native ALGO, not USDC
    v = verify_payment(_payload(reqs), reqs, tx_lookup=_lookup(tx), now=1100.0)
    assert not v.ok and v.reason == "wrong_asset_on_chain"


def test_unconfirmed_tx_rejected():
    reqs = _reqs()
    assert verify_payment(_payload(reqs), reqs, tx_lookup=_lookup(None), now=1100.0).reason == "tx_not_found_or_unconfirmed"
    tx0 = ConfirmedTx("ALICE", PAY_TO, 1_000_000, USDC_ASA_MAINNET, confirmed_round=0)
    assert verify_payment(_payload(reqs), reqs, tx_lookup=_lookup(tx0), now=1100.0).reason == "tx_unconfirmed"


def test_expired_requirements_rejected():
    reqs = _reqs(now=1000.0)  # expires at 1300
    tx = ConfirmedTx("ALICE", PAY_TO, 1_000_000, USDC_ASA_MAINNET, 42)
    v = verify_payment(_payload(reqs), reqs, tx_lookup=_lookup(tx), now=99999.0)
    assert not v.ok and v.reason == "requirements_expired"


def test_nonce_and_network_mismatch_rejected():
    reqs = _reqs()
    tx = ConfirmedTx("ALICE", PAY_TO, 1_000_000, USDC_ASA_MAINNET, 42)
    bad_nonce = PaymentPayload(reqs.network, reqs.asset, 1_000_000, "ALICE", "TX1", nonce="wrong")
    assert verify_payment(bad_nonce, reqs, tx_lookup=_lookup(tx), now=1100.0).reason == "nonce_mismatch"
    bad_net = PaymentPayload("algorand-testnet", reqs.asset, 1_000_000, "ALICE", "TX1", nonce=reqs.nonce)
    assert verify_payment(bad_net, reqs, tx_lookup=_lookup(tx), now=1100.0).reason == "network_mismatch"


def test_tx_replay_rejected():
    reqs = _reqs()
    tx = ConfirmedTx("ALICE", PAY_TO, 1_000_000, USDC_ASA_MAINNET, 42)
    seen: set = set()
    first = verify_payment(_payload(reqs, tx_id="TXR"), reqs, tx_lookup=_lookup(tx), seen_tx_ids=seen, now=1100.0)
    assert first.ok and "TXR" in seen
    second = verify_payment(_payload(reqs, tx_id="TXR"), reqs, tx_lookup=_lookup(tx), seen_tx_ids=seen, now=1100.0)
    assert not second.ok and second.reason == "tx_replay"


def test_requirements_payload_dict_roundtrip():
    reqs = _reqs()
    assert PaymentRequirements.from_dict(reqs.to_dict()) == reqs
    payload = _payload(reqs)
    assert PaymentPayload.from_dict(payload.to_dict()) == payload
