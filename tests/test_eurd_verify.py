"""Tests for the real on-chain EURD settlement verifier (merchant side)."""

from __future__ import annotations

from tenet.quantoz import make_settlement_verifier

PAY_TO = "MERCHANT"


class FakeIdx:
    """Stands in for an algosdk IndexerClient.search_transactions."""

    def __init__(self, txns):
        self._t = txns

    def search_transactions(self, **kw):
        return {"transactions": self._t}


def _axfer(txid, receiver, amount, sender="AGENT"):
    return {"id": txid, "sender": sender, "asset-transfer-transaction": {"receiver": receiver, "amount": amount}}


def test_settles_when_eurd_landed():
    v = make_settlement_verifier(FakeIdx([_axfer("T1", PAY_TO, 50)]), pay_to=PAY_TO, min_atomic=50)
    ok, payer = v(None)
    assert ok and payer == "AGENT"


def test_underpaid_rejected():
    v = make_settlement_verifier(FakeIdx([_axfer("T1", PAY_TO, 10)]), pay_to=PAY_TO, min_atomic=50)
    assert v(None) == (False, None)


def test_wrong_receiver_rejected():
    v = make_settlement_verifier(FakeIdx([_axfer("T1", "SOMEONE", 50)]), pay_to=PAY_TO, min_atomic=50)
    assert v(None) == (False, None)


def test_replay_blocked_across_requests():
    idx = FakeIdx([_axfer("T1", PAY_TO, 50)])
    seen: set = set()
    v = make_settlement_verifier(idx, pay_to=PAY_TO, min_atomic=50, seen=seen)
    assert v(None)[0] is True
    assert v(None) == (False, None)  # the same on-chain payment can't be reused


def test_indexer_failure_fails_closed():
    class Broken:
        def search_transactions(self, **kw):
            raise RuntimeError("indexer down")

    v = make_settlement_verifier(Broken(), pay_to=PAY_TO, min_atomic=50)
    assert v(None) == (False, None)
