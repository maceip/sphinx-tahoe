"""Tests for the unlinkable rate-limit token (blind-RSA + nullifier + cap)."""

from __future__ import annotations

import threading

import pytest

from tenet.blind_rsa import IssuerKey, i2osp
from tenet.rate_token import (
    IssuanceCap,
    NullifierLedger,
    RateLimitToken,
    TokenSpendError,
    begin_token,
    complete_token,
    issue_blind_sig,
    spend_token,
)


@pytest.fixture(scope="module")
def issuer():
    return IssuerKey.generate(bits=2048)


def _mint(issuer, *, identity="alice", epoch="e1", cap=None, max_n=None):
    cap = cap or IssuanceCap()
    req = begin_token(issuer.public)
    blind_sig = issue_blind_sig(issuer, req.blinded_msg, identity=identity, epoch=epoch, cap=cap, max_n=max_n)
    return complete_token(issuer.public, req, blind_sig)


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #


def test_full_issue_and_spend(issuer):
    token = _mint(issuer)
    ledger = NullifierLedger()
    nf = spend_token(issuer.public, token, ledger)
    assert ledger.is_spent(nf)
    assert ledger.count() == 1


def test_double_spend_blocked(issuer):
    token = _mint(issuer)
    ledger = NullifierLedger()
    spend_token(issuer.public, token, ledger)
    with pytest.raises(TokenSpendError, match="double-spend"):
        spend_token(issuer.public, token, ledger)


def test_forged_token_rejected(issuer):
    forged = RateLimitToken(prepared_msg=b"\x00" * 64, signature=i2osp(42, issuer.public.modulus_len))
    ledger = NullifierLedger()
    with pytest.raises(TokenSpendError, match="does not verify"):
        spend_token(issuer.public, forged, ledger)


def test_token_from_other_issuer_rejected(issuer):
    other = IssuerKey.generate(bits=2048)
    token = _mint(other)  # validly minted, but by a different issuer
    ledger = NullifierLedger()
    with pytest.raises(TokenSpendError, match="does not verify"):
        spend_token(issuer.public, token, ledger)


# --------------------------------------------------------------------------- #
# issuance cap (the sybil/rate limit)
# --------------------------------------------------------------------------- #


def test_issuance_cap_enforced(issuer):
    cap = IssuanceCap(default_max=3)
    for _ in range(3):
        _mint(issuer, identity="bob", epoch="e1", cap=cap)
    assert cap.issued("bob", "e1") == 3
    # the 4th issuance is refused
    req = begin_token(issuer.public)
    with pytest.raises(TokenSpendError, match="cap reached"):
        issue_blind_sig(issuer, req.blinded_msg, identity="bob", epoch="e1", cap=cap)


def test_cap_is_per_identity_and_epoch(issuer):
    cap = IssuanceCap(default_max=1)
    _mint(issuer, identity="carol", epoch="e1", cap=cap)
    # same identity, new epoch -> allowed again
    _mint(issuer, identity="carol", epoch="e2", cap=cap)
    # different identity, same epoch -> allowed
    _mint(issuer, identity="dave", epoch="e1", cap=cap)
    assert cap.issued("carol", "e1") == 1
    assert cap.issued("carol", "e2") == 1
    assert cap.issued("dave", "e1") == 1


def test_cap_atomic_under_concurrency(issuer):
    cap = IssuanceCap(default_max=10)
    successes: list[bool] = []
    lock = threading.Lock()

    def worker():
        ok = cap.try_issue("eve", "e1", max_n=10)
        with lock:
            successes.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # exactly 10 succeed despite 50 concurrent attempts
    assert sum(successes) == 10
    assert cap.issued("eve", "e1") == 10


# --------------------------------------------------------------------------- #
# unlinkability + durability
# --------------------------------------------------------------------------- #


def test_issuer_view_is_unlinkable_to_spend(issuer):
    cap = IssuanceCap()
    req = begin_token(issuer.public)
    issuer_saw = req.blinded_msg
    blind_sig = issue_blind_sig(issuer, req.blinded_msg, identity="x", epoch="e", cap=cap)
    token = complete_token(issuer.public, req, blind_sig)
    # what the issuer signed is not what is presented at spend
    assert issuer_saw != token.prepared_msg
    assert issuer_saw != token.signature
    # the nullifier the verifier records is not derivable from the issuer's view
    import hashlib

    assert token.nullifier != hashlib.sha256(issuer_saw).hexdigest()


def test_nullifier_durable_across_restart(issuer, tmp_path):
    db = str(tmp_path / "nullifiers.db")
    token = _mint(issuer)
    ledger = NullifierLedger(db)
    nf = spend_token(issuer.public, token, ledger)
    ledger.close()
    # reopen: the spend persisted, so a replay is still blocked
    ledger2 = NullifierLedger(db)
    assert ledger2.is_spent(nf)
    with pytest.raises(TokenSpendError, match="double-spend"):
        spend_token(issuer.public, token, ledger2)
    ledger2.close()


def test_cap_durable_across_restart(issuer, tmp_path):
    db = str(tmp_path / "cap.db")
    cap = IssuanceCap(db, default_max=2)
    cap.try_issue("frank", "e1")
    cap.close()
    cap2 = IssuanceCap(db, default_max=2)
    assert cap2.issued("frank", "e1") == 1
    cap2.try_issue("frank", "e1")
    assert cap2.try_issue("frank", "e1") is False  # cap of 2 reached
    cap2.close()
