"""Integration: blind-token issuer key committed in the signed pool descriptor.

Proves a token is only spendable under the key the pool published in its *signed*
control record, end to end through the policy/record machinery.
"""

from __future__ import annotations

import pytest
from nacl.signing import SigningKey

from tenet.blind_rsa import IssuerKey
from tenet.mixnet.control.pools import PoolDescriptor
from tenet.mixnet.control.records import sign_control_record
from tenet.mixnet.control.service import MixnetControlService
from tenet.rate_token import (
    IssuanceCap,
    NullifierLedger,
    TokenSpendError,
    begin_token,
    complete_token,
    issue_blind_sig,
    spend_token_for_pool,
)

POOL = "soup.expert~tenet"


@pytest.fixture(scope="module")
def issuer():
    return IssuerKey.generate(bits=2048)


def _pool_descriptor(issuer):
    return PoolDescriptor(
        name=POOL,
        topic_tags=("soup",),
        arc_issuer_key_pem=issuer.public.to_pem().decode("utf-8"),
        pay_to="ALGO_ADDR_DEMO",
        token_epoch="2026-06",
        queries_per_token=5,
    )


def _mint(issuer):
    cap = IssuanceCap()
    req = begin_token(issuer.public)
    blind_sig = issue_blind_sig(issuer, req.blinded_msg, identity="alice", epoch="2026-06", cap=cap)
    return complete_token(issuer.public, req, blind_sig)


def test_descriptor_carries_issuer_key_and_roundtrips(issuer):
    pd = _pool_descriptor(issuer)
    pd.validate()
    back = PoolDescriptor.from_dict(pd.to_dict())
    assert back.issuer_public_key().n == issuer.public.n
    assert back.pay_to == "ALGO_ADDR_DEMO"
    assert back.queries_per_token == 5


def test_invalid_issuer_key_rejected():
    with pytest.raises(ValueError, match="invalid arc_issuer_key_pem"):
        PoolDescriptor(name=POOL, topic_tags=("soup",), arc_issuer_key_pem="-----BEGIN nonsense-----").validate()


def test_token_spends_under_descriptor_committed_key_via_signed_record(issuer):
    # 1. publish the pool descriptor as a SIGNED control record (policy-validated)
    sk = SigningKey.generate()
    svc = MixnetControlService(network_id="net", verify_keys={"root": sk.verify_key.encode().hex()})
    pd = _pool_descriptor(issuer)
    svc.put_signed(sign_control_record(
        svc.make_unsigned_pool_descriptor(pd, seq=1), signing_key_hex=sk.encode().hex(), key_id="root",
    ))
    # 2. resolve the descriptor back from the service
    resolved = svc.pool_descriptor(POOL)
    assert resolved is not None and resolved.issuer_public_key() is not None
    # 3. a token minted by the committed issuer spends OK under the resolved key
    token = _mint(issuer)
    ledger = NullifierLedger()
    nf = spend_token_for_pool(resolved, token, ledger)
    assert ledger.is_spent(nf)


def test_token_from_other_issuer_rejected_under_committed_key(issuer):
    other = IssuerKey.generate(bits=2048)
    pd = _pool_descriptor(issuer)  # commits `issuer`, not `other`
    token = _mint(other)           # minted by the wrong issuer
    ledger = NullifierLedger()
    with pytest.raises(TokenSpendError, match="does not verify"):
        spend_token_for_pool(pd, token, ledger)


def test_pool_without_arc_issuer_rejects_spend():
    pd = PoolDescriptor(name=POOL, topic_tags=("soup",))  # no issuer committed
    token_like = _mint(IssuerKey.generate(bits=2048))
    ledger = NullifierLedger()
    with pytest.raises(TokenSpendError, match="commits no ARC issuer"):
        spend_token_for_pool(pd, token_like, ledger)
