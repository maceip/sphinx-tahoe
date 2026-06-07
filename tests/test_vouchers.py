"""Tests for the prepaid anonymous voucher token (hackathon demo stand-in).

This is the Phase-1 rate-limit token: a MAC-signed prepaid ticket with a one-time
nullifier. (Real blind signatures replace the MAC later — see the design memory.)
"""

from __future__ import annotations

import pytest

from tenet.vouchers import (
    VOUCHER_VERSION,
    Voucher,
    issue_voucher_batch,
    redeem_ticket,
)

SECRET = b"issuer-secret-32-bytes-demo-only!"


def test_issue_and_redeem_happy_path():
    v = issue_voucher_batch(queries=3, issuer_secret=SECRET, pool="soup.expert~tenet", pay_tx="ALGO_TX_1")
    assert v.remaining() == 3
    spent: set[str] = set()
    ticket = v.tickets[0]
    v2, nf = redeem_ticket(v, ticket.token, ticket.mac, SECRET, spent)
    assert v2.remaining() == 2
    assert nf in spent


def test_double_spend_rejected():
    v = issue_voucher_batch(queries=2, issuer_secret=SECRET, pay_tx="ALGO_TX_2")
    spent: set[str] = set()
    ticket = v.tickets[0]
    v2, _nf = redeem_ticket(v, ticket.token, ticket.mac, SECRET, spent)
    # replaying the same ticket against the spent-nullifier set is refused
    with pytest.raises(ValueError, match="already spent"):
        redeem_ticket(v, ticket.token, ticket.mac, SECRET, spent)


def test_forged_mac_rejected():
    v = issue_voucher_batch(queries=1, issuer_secret=SECRET, pay_tx="ALGO_TX_3")
    spent: set[str] = set()
    ticket = v.tickets[0]
    with pytest.raises(ValueError, match="invalid ticket mac"):
        redeem_ticket(v, ticket.token, "00" * 32, SECRET, spent)


def test_no_pay_tx_does_not_crash():
    # regression: `pay_tx or ""` precedence used to TypeError when pay_tx is None
    v = issue_voucher_batch(queries=1, issuer_secret=SECRET, pay_tx=None)
    spent: set[str] = set()
    ticket = v.tickets[0]
    v2, nf = redeem_ticket(v, ticket.token, ticket.mac, SECRET, spent)
    assert v2.remaining() == 0 and nf in spent


def test_nullifier_consistent_between_issue_and_redeem():
    # the nullifier minted at issue time must match the one computed at redeem
    v = issue_voucher_batch(queries=1, issuer_secret=SECRET, pay_tx="ALGO_TX_4")
    spent: set[str] = set()
    ticket = v.tickets[0]
    _v2, nf = redeem_ticket(v, ticket.token, ticket.mac, SECRET, spent)
    assert nf == ticket.nullifier


def test_voucher_json_roundtrip():
    v = issue_voucher_batch(queries=2, issuer_secret=SECRET, pool="p~tenet", pay_tx="TX")
    back = Voucher.from_json(v.to_json())
    assert back.version == VOUCHER_VERSION
    assert back.remaining() == 2
    assert back.tickets[0].token == v.tickets[0].token


def test_more_tickets_than_queries_rejected():
    v = issue_voucher_batch(queries=1, issuer_secret=SECRET, pay_tx="TX")
    bad = Voucher(
        version=v.version, queries=1, pool=None, pay_tx="TX",
        tickets=v.tickets + v.tickets, issued_at=v.issued_at,
    )
    with pytest.raises(ValueError, match="more tickets than queries"):
        bad.validate()
