"""Tests for RFC 9474 RSABSSA blind RSA signatures.

Correctness is validated against the vetted ``cryptography`` library's RSASSA-PSS
verifier — if a signature produced via our blind path verifies as a standard PSS
signature, then EMSA-PSS-ENCODE, the blinding, and finalize are all correct.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from tenet.blind_rsa import (
    BlindSignatureError,
    IssuerKey,
    SALT_LEN,
    blind,
    emsa_pss_encode,
    finalize,
    i2osp,
    os2ip,
    prepare,
)

MSG = b"tenet-rate-limit-token-001"


@pytest.fixture(scope="module")
def issuer():
    # 2048-bit key generated once for the module (keygen is the slow part).
    return IssuerKey.generate(bits=2048)


# --------------------------------------------------------------------------- #
# the headline: blind round-trip yields a real PSS signature
# --------------------------------------------------------------------------- #


def test_blind_round_trip_produces_valid_pss_signature(issuer):
    pub = issuer.public
    prepared = prepare(MSG)
    blinded, inv = blind(pub, prepared)
    blind_sig = issuer.blind_sign(blinded)
    sig = finalize(pub, prepared, blind_sig, inv)
    # verified inside finalize, but assert independently via the library oracle
    assert pub.verify(prepared, sig) is True
    pub._crypto_pub().verify(
        sig, prepared,
        padding.PSS(mgf=padding.MGF1(hashes.SHA384()), salt_length=SALT_LEN),
        hashes.SHA384(),
    )  # raises if invalid


def test_emsa_pss_encode_matches_library_pss(issuer):
    """Direct sign of our EMSA-PSS-ENCODE output verifies under the library —
    proves our hand-rolled PSS encoding is byte-correct."""
    pub = issuer.public
    em_bits = pub.n.bit_length() - 1
    encoded = emsa_pss_encode(MSG, em_bits)
    m = os2ip(encoded)
    s = pow(m, issuer._d, pub.n)  # raw RSA sign of the encoded message
    sig = i2osp(s, pub.modulus_len)
    assert pub.verify(MSG, sig) is True


# --------------------------------------------------------------------------- #
# unlinkability + determinism
# --------------------------------------------------------------------------- #


def test_blinding_is_randomized_each_time(issuer):
    pub = issuer.public
    prepared = prepare(MSG)
    b1, _ = blind(pub, prepared)
    b2, _ = blind(pub, prepared)
    # different salt + blind factor each time => issuer's view differs
    assert b1 != b2


def test_deterministic_with_injected_salt_and_blind(issuer):
    pub = issuer.public
    prepared = prepare(MSG, randomizer=b"\x11" * 32)
    salt = b"\x22" * SALT_LEN
    r = 0x123456789ABCDEF % pub.n or 3
    b1, inv1 = blind(pub, prepared, salt=salt, blind_r=r)
    b2, inv2 = blind(pub, prepared, salt=salt, blind_r=r)
    assert b1 == b2 and inv1 == inv2
    # and it still finalizes to a valid signature
    sig = finalize(pub, prepared, issuer.blind_sign(b1), inv1)
    assert pub.verify(prepared, sig)


# --------------------------------------------------------------------------- #
# forgery / tamper / fail-closed
# --------------------------------------------------------------------------- #


def test_forged_signature_rejected(issuer):
    pub = issuer.public
    prepared = prepare(MSG)
    forged = i2osp(12345, pub.modulus_len)
    assert pub.verify(prepared, forged) is False


def test_signature_from_other_issuer_rejected(issuer):
    other = IssuerKey.generate(bits=2048)
    prepared = prepare(MSG)
    blinded, inv = blind(other.public, prepared)
    sig = finalize(other.public, prepared, other.blind_sign(blinded), inv)
    # valid under `other`, but NOT under the real issuer's key
    assert other.public.verify(prepared, sig) is True
    assert issuer.public.verify(prepared, sig) is False


def test_tampered_message_rejected(issuer):
    pub = issuer.public
    prepared = prepare(MSG)
    blinded, inv = blind(pub, prepared)
    sig = finalize(pub, prepared, issuer.blind_sign(blinded), inv)
    assert pub.verify(prepared + b"x", sig) is False


def test_blind_sign_wrong_size_fails(issuer):
    with pytest.raises(BlindSignatureError, match="size"):
        issuer.blind_sign(b"too short")


def test_finalize_with_wrong_inverse_fails(issuer):
    pub = issuer.public
    prepared = prepare(MSG)
    blinded, _inv = blind(pub, prepared)
    blind_sig = issuer.blind_sign(blinded)
    with pytest.raises(BlindSignatureError, match="invalid signature"):
        finalize(pub, prepared, blind_sig, inv=2)  # wrong unblind factor


def test_public_key_pem_roundtrip(issuer):
    pem = issuer.public.to_pem()
    from tenet.blind_rsa import IssuerPublicKey

    back = IssuerPublicKey.from_pem(pem)
    assert back.n == issuer.public.n and back.e == issuer.public.e
