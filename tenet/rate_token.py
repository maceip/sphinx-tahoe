"""Unlinkable rate-limit token built on RFC 9474 blind RSA.

This is the Phase-1 token: privacy + subsidy-abuse (sybil) control, nothing more.

- **Issuance is capped** per (identity, epoch) at the issuer — this is the only
  point that sees an identity, so the sybil/rate limit lives here.
- **Spend is unlinkable** — the presented (prepared_msg, signature) carries no
  identity, and the issuer never saw it. Double-spend is stopped by a one-time
  **nullifier** recorded in a durable, concurrency-safe SQLite ledger.

The unforgeability + unlinkability come from the blind signature; this module
adds the spend bookkeeping and the issuance cap.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass

from tenet.blind_rsa import (
    BlindSignatureError,
    IssuerKey,
    IssuerPublicKey,
    blind,
    finalize,
    prepare,
)


def _nullifier(prepared_msg: bytes) -> str:
    return hashlib.sha256(b"tenet.rate_token.nullifier\x00" + prepared_msg).hexdigest()


# --------------------------------------------------------------------------- #
# token presentation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RateLimitToken:
    """A finalized, spendable token: the prepared message + its blind signature.

    Carries no identity and is unlinkable to its issuance.
    """

    prepared_msg: bytes
    signature: bytes

    @property
    def nullifier(self) -> str:
        return _nullifier(self.prepared_msg)

    def to_dict(self) -> dict[str, str]:
        return {"m": self.prepared_msg.hex(), "s": self.signature.hex()}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "RateLimitToken":
        return cls(prepared_msg=bytes.fromhex(d["m"]), signature=bytes.fromhex(d["s"]))


@dataclass(frozen=True)
class TokenRequest:
    """Client-side blinding state kept between Blind and Finalize."""

    prepared_msg: bytes
    blinded_msg: bytes
    _inv: int


def begin_token(pub: IssuerPublicKey) -> TokenRequest:
    """Client step 1: generate a fresh token secret, prepare + blind it."""
    secret = os.urandom(32)
    prepared = prepare(secret)
    blinded, inv = blind(pub, prepared)
    return TokenRequest(prepared_msg=prepared, blinded_msg=blinded, _inv=inv)


def complete_token(pub: IssuerPublicKey, request: TokenRequest, blind_sig: bytes) -> RateLimitToken:
    """Client step 2: unblind the issuer's blind signature into a usable token."""
    sig = finalize(pub, request.prepared_msg, blind_sig, request._inv)
    return RateLimitToken(prepared_msg=request.prepared_msg, signature=sig)


# --------------------------------------------------------------------------- #
# nullifier ledger (durable, concurrency-safe)
# --------------------------------------------------------------------------- #


class NullifierLedger:
    """One-time spend ledger. A UNIQUE constraint makes double-spend atomic."""

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS nullifiers (nf TEXT PRIMARY KEY, spent_at REAL)"
        )
        self._conn.commit()

    def try_spend(self, nullifier: str, *, now: float | None = None) -> bool:
        """Atomically mark a nullifier spent. Returns False if already spent."""
        ts = time.time() if now is None else now
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO nullifiers (nf, spent_at) VALUES (?, ?)", (nullifier, ts)
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def is_spent(self, nullifier: str) -> bool:
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM nullifiers WHERE nf = ?", (nullifier,))
            return cur.fetchone() is not None

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM nullifiers").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# --------------------------------------------------------------------------- #
# issuance cap (per identity / epoch)
# --------------------------------------------------------------------------- #


class IssuanceCap:
    """Per-(identity, epoch) issuance counter — the sybil/rate limit lives here."""

    def __init__(self, path: str = ":memory:", *, default_max: int = 100) -> None:
        self.default_max = int(default_max)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS issuance "
            "(identity TEXT, epoch TEXT, count INTEGER, PRIMARY KEY (identity, epoch))"
        )
        self._conn.commit()

    def try_issue(self, identity: str, epoch: str, *, max_n: int | None = None) -> bool:
        """Atomically reserve one issuance under the cap. False if cap reached."""
        cap = self.default_max if max_n is None else int(max_n)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT count FROM issuance WHERE identity = ? AND epoch = ?",
                    (identity, epoch),
                ).fetchone()
                current = row[0] if row else 0
                if current >= cap:
                    self._conn.execute("ROLLBACK")
                    return False
                if row:
                    self._conn.execute(
                        "UPDATE issuance SET count = count + 1 WHERE identity = ? AND epoch = ?",
                        (identity, epoch),
                    )
                else:
                    self._conn.execute(
                        "INSERT INTO issuance (identity, epoch, count) VALUES (?, ?, 1)",
                        (identity, epoch),
                    )
                self._conn.execute("COMMIT")
                return True
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def issued(self, identity: str, epoch: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM issuance WHERE identity = ? AND epoch = ?",
                (identity, epoch),
            ).fetchone()
            return row[0] if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# --------------------------------------------------------------------------- #
# issuer-side + verifier-side glue
# --------------------------------------------------------------------------- #


class TokenSpendError(ValueError):
    """Raised when a token cannot be spent (bad signature or already spent)."""


def issue_blind_sig(
    issuer: IssuerKey,
    blinded_msg: bytes,
    *,
    identity: str,
    epoch: str,
    cap: IssuanceCap,
    max_n: int | None = None,
) -> bytes:
    """Issuer: enforce the per-identity/epoch cap, then blind-sign.

    The cap is the *only* place an identity is observed; the resulting token is
    unlinkable. Reserves the cap slot before signing so it can't be exceeded.
    """
    if not cap.try_issue(identity, epoch, max_n=max_n):
        raise TokenSpendError("issuance cap reached for identity/epoch")
    try:
        return issuer.blind_sign(blinded_msg)
    except BlindSignatureError:
        raise


def spend_token_for_pool(
    pool_descriptor,
    token: RateLimitToken,
    ledger: NullifierLedger,
    *,
    now: float | None = None,
) -> str:
    """Spend a token under the issuer key *committed in the signed pool descriptor*.

    This is the control-plane binding: a token is only valid if it verifies under
    the key the pool published in its signed record — not any issuer the holder
    chooses.
    """
    pub = pool_descriptor.issuer_public_key()
    if pub is None:
        raise TokenSpendError("pool descriptor commits no ARC issuer key")
    return spend_token(pub, token, ledger, now=now)


def spend_token(
    pub: IssuerPublicKey,
    token: RateLimitToken,
    ledger: NullifierLedger,
    *,
    now: float | None = None,
) -> str:
    """Verifier: verify the token's signature, then atomically burn its nullifier.

    Returns the nullifier on success; raises TokenSpendError on a forged token or
    a double-spend.
    """
    if not pub.verify(token.prepared_msg, token.signature):
        raise TokenSpendError("token signature does not verify under issuer key")
    nf = token.nullifier
    if not ledger.try_spend(nf, now=now):
        raise TokenSpendError("token already spent (double-spend)")
    return nf
