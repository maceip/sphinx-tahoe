"""Privacy Pass-style anonymous transferable vouchers for N queries.

Voucher packets are email-able JSON files containing pre-paid tickets.
- Pre-pay on Algorand (visible tx to pool payTo) before issuance.
- Tickets are random, MAC-signed by issuer secret at sponsor time.
- Transferable by sharing the file; no PII or email embedded.
- Redemption uses nullifier (one-time); tickets gone after use.
- Unlinkable to distribution channel (nullifiers only on spend).
- Demo only; real blind signatures (Privacy Pass) can replace MAC later.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

VOUCHER_VERSION = 1


@dataclass(frozen=True)
class Ticket:
    token: str  # hex random
    mac: str    # hex HMAC(token, issuer_secret)
    nullifier: str  # hex sha256(token + "spent")

    def to_dict(self) -> dict[str, str]:
        return {"t": self.token, "m": self.mac, "n": self.nullifier}

    @classmethod
    def from_dict(cls, d: Mapping[str, str]) -> "Ticket":
        return cls(token=d["t"], mac=d["m"], nullifier=d["n"])


@dataclass(frozen=True)
class Voucher:
    version: int
    queries: int
    pool: str | None  # optional pool name for scoped pay
    pay_tx: str | None  # Algorand txid of pre-pay (visible on explorer)
    tickets: tuple[Ticket, ...]
    issued_at: float

    def to_json(self) -> str:
        return json.dumps({
            "v": self.version,
            "q": self.queries,
            "pool": self.pool,
            "pay_tx": self.pay_tx,
            "tickets": [t.to_dict() for t in self.tickets],
            "issued": self.issued_at,
        }, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "Voucher":
        raw = json.loads(s)
        return cls(
            version=int(raw.get("v", 0)),
            queries=int(raw.get("q", 0)),
            pool=raw.get("pool"),
            pay_tx=raw.get("pay_tx"),
            tickets=tuple(Ticket.from_dict(x) for x in raw.get("tickets", [])),
            issued_at=float(raw.get("issued", 0)),
        )

    def remaining(self) -> int:
        return len(self.tickets)

    def validate(self) -> None:
        if self.version != VOUCHER_VERSION:
            raise ValueError("unsupported voucher version")
        if self.queries < 0:
            raise ValueError("queries must be non-negative")
        if len(self.tickets) > self.queries:
            raise ValueError("more tickets than queries granted")


def _hmac(key: bytes, msg: bytes) -> str:
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def issue_voucher_batch(
    *,
    queries: int,
    issuer_secret: bytes,
    pool: str | None = None,
    pay_tx: str | None = None,
    now: float | None = None,
) -> Voucher:
    """Sponsor issues N tickets after pre-paying on Algorand to pool payTo."""
    if queries <= 0:
        raise ValueError("queries must be positive")
    if len(issuer_secret) < 16:
        raise ValueError("issuer_secret too short")
    tickets: list[Ticket] = []
    for _ in range(queries):
        token = os.urandom(16).hex()
        mac = _hmac(issuer_secret, token.encode())
        nf = hashlib.sha256((token + "spent" + (pay_tx or "")).encode()).hexdigest()
        tickets.append(Ticket(token=token, mac=mac, nullifier=nf))
    v = Voucher(
        version=VOUCHER_VERSION,
        queries=queries,
        pool=pool,
        pay_tx=pay_tx,
        tickets=tuple(tickets),
        issued_at=now or time.time(),
    )
    v.validate()
    return v


def redeem_ticket(
    voucher: Voucher,
    token: str,
    mac: str,
    issuer_secret: bytes,
    spent_nullifiers: set[str],
) -> tuple[Voucher, str]:
    """Consume one ticket if valid and unspent. Returns new voucher + nullifier."""
    nf = hashlib.sha256((token + "spent" + (voucher.pay_tx or "")).encode()).hexdigest()
    if nf in spent_nullifiers:
        raise ValueError("ticket already spent")
    expected_mac = _hmac(issuer_secret, token.encode())
    if not hmac.compare_digest(expected_mac, mac):
        raise ValueError("invalid ticket mac")
    # find and remove the ticket
    remaining = [t for t in voucher.tickets if not (t.token == token and t.mac == mac)]
    if len(remaining) == len(voucher.tickets):
        raise ValueError("ticket not in voucher")
    new_v = Voucher(
        version=voucher.version,
        queries=voucher.queries,
        pool=voucher.pool,
        pay_tx=voucher.pay_tx,
        tickets=tuple(remaining),
        issued_at=voucher.issued_at,
    )
    spent_nullifiers.add(nf)
    return new_v, nf


def load_voucher(path: str | Path) -> Voucher:
    return Voucher.from_json(Path(path).read_text(encoding="utf-8"))


def save_voucher(v: Voucher, path: str | Path) -> None:
    Path(path).write_text(v.to_json() + "\n", encoding="utf-8")
