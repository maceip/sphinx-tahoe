"""RFC 9474 RSABSSA blind RSA signatures (RSABSSA-SHA384-PSS).

A real, unlinkable blind signature: the issuer signs a *blinded* message it never
sees, the client unblinds to a standard RSASSA-PSS signature, and issuance is
cryptographically unlinkable from the later (token, signature) presentation.

We build on the vetted ``cryptography`` library for RSA key generation and for
RSASSA-PSS *verification* (the finalized signature is an ordinary PSS signature,
so the library's verifier is the correctness oracle). We hand-implement only the
pieces RFC 9474 needs that the library does not expose: EMSA-PSS-ENCODE
(RFC 8017 §9.1.1) and the blinding/finalize modular arithmetic. ``salt`` and the
randomizer are injectable so the path is deterministic for tests / RFC vectors.

Variant: RSABSSA-SHA384-PSS-Randomized — SHA-384, MGF1-SHA-384, salt_len 48,
32-byte random prepare prefix (RFC 9474 §5).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

HASH = hashlib.sha384
H_LEN = 48          # SHA-384 output length
SALT_LEN = 48       # RSABSSA-SHA384 salt length
PREPARE_PREFIX_LEN = 32  # RSABSSA-*-Randomized prepares msg with 32 random bytes


class BlindSignatureError(ValueError):
    """Raised on any blind-signature protocol failure (fail closed)."""


# --------------------------------------------------------------------------- #
# RFC 8017 primitives
# --------------------------------------------------------------------------- #


def i2osp(x: int, length: int) -> bytes:
    if x < 0 or x >= (1 << (8 * length)):
        raise BlindSignatureError("integer too large for I2OSP")
    return x.to_bytes(length, "big")


def os2ip(data: bytes) -> int:
    return int.from_bytes(data, "big")


def _mgf1(seed: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += HASH(seed + i2osp(counter, 4)).digest()
        counter += 1
    return out[:length]


def emsa_pss_encode(msg: bytes, em_bits: int, *, salt: bytes | None = None) -> bytes:
    """EMSA-PSS-ENCODE (RFC 8017 §9.1.1) with SHA-384 / MGF1-SHA-384."""
    m_hash = HASH(msg).digest()
    em_len = (em_bits + 7) // 8
    if salt is None:
        salt = os.urandom(SALT_LEN)
    if len(salt) != SALT_LEN:
        raise BlindSignatureError("salt length mismatch")
    if em_len < H_LEN + SALT_LEN + 2:
        raise BlindSignatureError("encoding error: modulus too small")
    m_prime = b"\x00" * 8 + m_hash + salt
    h = HASH(m_prime).digest()
    ps = b"\x00" * (em_len - SALT_LEN - H_LEN - 2)
    db = ps + b"\x01" + salt
    db_mask = _mgf1(h, em_len - H_LEN - 1)
    masked_db = bytes(a ^ b for a, b in zip(db, db_mask))
    # zero the leftmost (8*em_len - em_bits) bits
    bits_to_clear = 8 * em_len - em_bits
    masked = bytearray(masked_db)
    masked[0] &= 0xFF >> bits_to_clear
    return bytes(masked) + h + b"\xbc"


# --------------------------------------------------------------------------- #
# keys
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IssuerPublicKey:
    n: int
    e: int

    @property
    def modulus_len(self) -> int:
        return (self.n.bit_length() + 7) // 8

    def to_pem(self) -> bytes:
        pub = rsa.RSAPublicNumbers(self.e, self.n).public_key()
        from cryptography.hazmat.primitives import serialization

        return pub.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    @classmethod
    def from_pem(cls, pem: bytes) -> "IssuerPublicKey":
        from cryptography.hazmat.primitives import serialization

        pub = serialization.load_pem_public_key(pem)
        nums = pub.public_numbers()
        return cls(n=nums.n, e=nums.e)

    def _crypto_pub(self):
        return rsa.RSAPublicNumbers(self.e, self.n).public_key()

    def verify(self, prepared_msg: bytes, sig: bytes) -> bool:
        """Standard RSASSA-PSS verification (the finalized blind sig is ordinary)."""
        try:
            self._crypto_pub().verify(
                sig,
                prepared_msg,
                padding.PSS(mgf=padding.MGF1(hashes.SHA384()), salt_length=SALT_LEN),
                hashes.SHA384(),
            )
            return True
        except InvalidSignature:
            return False


class IssuerKey:
    """Issuer secret key. Blind-signs after (out of band) confirming payment."""

    def __init__(self, private_key: rsa.RSAPrivateKey) -> None:
        self._sk = private_key
        nums = private_key.private_numbers()
        self._d = nums.d
        self.public = IssuerPublicKey(n=nums.public_numbers.n, e=nums.public_numbers.e)

    @classmethod
    def generate(cls, bits: int = 2048) -> "IssuerKey":
        return cls(rsa.generate_private_key(public_exponent=65537, key_size=bits))

    def blind_sign(self, blinded_msg: bytes) -> bytes:
        """BlindSign (RFC 9474 §5.1.2): raw RSA private op on the blinded message."""
        pub = self.public
        if len(blinded_msg) != pub.modulus_len:
            raise BlindSignatureError("unexpected blinded message size")
        m = os2ip(blinded_msg)
        if m >= pub.n:
            raise BlindSignatureError("blinded message out of range")
        s = pow(m, self._d, pub.n)
        # self-check (RFC 9474): m == s^e mod n
        if pow(s, pub.e, pub.n) != m:
            raise BlindSignatureError("signing failure")
        return i2osp(s, pub.modulus_len)


# --------------------------------------------------------------------------- #
# client protocol
# --------------------------------------------------------------------------- #


def prepare(msg: bytes, *, randomizer: bytes | None = None) -> bytes:
    """PrepareRandomize (RFC 9474): 32 random bytes prepended to the message."""
    if randomizer is None:
        randomizer = os.urandom(PREPARE_PREFIX_LEN)
    if len(randomizer) != PREPARE_PREFIX_LEN:
        raise BlindSignatureError("randomizer length mismatch")
    return randomizer + msg


def blind(
    pub: IssuerPublicKey,
    prepared_msg: bytes,
    *,
    salt: bytes | None = None,
    blind_r: int | None = None,
) -> tuple[bytes, int]:
    """Blind (RFC 9474 §5.1.1). Returns (blinded_msg, inverse) for Finalize."""
    em_bits = pub.n.bit_length() - 1
    encoded = emsa_pss_encode(prepared_msg, em_bits, salt=salt)
    m = os2ip(encoded)
    import math

    if math.gcd(m, pub.n) != 1:
        raise BlindSignatureError("invalid input (not coprime to modulus)")
    while True:
        r = blind_r if blind_r is not None else int.from_bytes(os.urandom(pub.modulus_len), "big") % pub.n
        if r == 0:
            if blind_r is not None:
                raise BlindSignatureError("invalid blind r")
            continue
        try:
            inv = pow(r, -1, pub.n)
        except ValueError:
            if blind_r is not None:
                raise BlindSignatureError("blind r not invertible")
            continue
        break
    x = pow(r, pub.e, pub.n)
    z = (m * x) % pub.n
    return i2osp(z, pub.modulus_len), inv


def finalize(
    pub: IssuerPublicKey,
    prepared_msg: bytes,
    blind_sig: bytes,
    inv: int,
) -> bytes:
    """Finalize (RFC 9474 §5.1.3): unblind and verify the standard PSS signature."""
    if len(blind_sig) != pub.modulus_len:
        raise BlindSignatureError("unexpected blind signature size")
    z = os2ip(blind_sig)
    s = (z * inv) % pub.n
    sig = i2osp(s, pub.modulus_len)
    if not pub.verify(prepared_msg, sig):
        raise BlindSignatureError("invalid signature after finalize")
    return sig
