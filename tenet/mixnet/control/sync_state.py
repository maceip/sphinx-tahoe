"""Persistent anti-entropy state for control-record sync (Item 4).

Tracks, per prefix, how far a client has synced (cursor) and when it last
refreshed, and tracks per-peer failure backoff so a dead or hostile peer is not
hammered every cycle. This is the bookkeeping that lets a daemon-mode client run
a safe, bounded anti-entropy loop instead of re-pulling everything every time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PeerSyncHealth:
    failures: int = 0
    next_retry_after: float = 0.0  # epoch seconds; peer is skipped until then

    def to_dict(self) -> dict[str, object]:
        return {"failures": self.failures, "next_retry_after": self.next_retry_after}

    @classmethod
    def from_dict(cls, raw: dict) -> "PeerSyncHealth":
        return cls(
            failures=int(raw.get("failures", 0)),
            next_retry_after=float(raw.get("next_retry_after", 0.0)),
        )


@dataclass
class ControlSyncState:
    """Per-prefix cursors + per-peer backoff, optionally persisted to JSON."""

    cursors: dict[str, str] = field(default_factory=dict)
    last_refresh: dict[str, float] = field(default_factory=dict)
    peers: dict[str, PeerSyncHealth] = field(default_factory=dict)
    path: Path | None = None

    # cursor / refresh ----------------------------------------------------- #

    def cursor(self, prefix: str) -> str:
        return self.cursors.get(prefix, "")

    def set_cursor(self, prefix: str, cursor: str) -> None:
        self.cursors[prefix] = cursor

    def mark_refreshed(self, prefix: str, now: float) -> None:
        self.last_refresh[prefix] = now

    def due(self, prefix: str, interval: float, now: float) -> bool:
        """True if ``prefix`` has not refreshed within ``interval`` seconds."""
        last = self.last_refresh.get(prefix)
        return last is None or (now - last) >= interval

    # peer backoff --------------------------------------------------------- #

    def peer_available(self, peer: str, now: float) -> bool:
        health = self.peers.get(peer)
        return health is None or now >= health.next_retry_after

    def record_peer_failure(self, peer: str, now: float, *, base_backoff: float = 1.0, max_backoff: float = 300.0) -> None:
        health = self.peers.setdefault(peer, PeerSyncHealth())
        health.failures += 1
        # exponential backoff capped at max_backoff
        delay = min(max_backoff, base_backoff * (2 ** (health.failures - 1)))
        health.next_retry_after = now + delay

    def record_peer_success(self, peer: str) -> None:
        self.peers[peer] = PeerSyncHealth(failures=0, next_retry_after=0.0)

    # persistence ---------------------------------------------------------- #

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tenet.control_sync_state.2026-06",
            "cursors": dict(self.cursors),
            "last_refresh": dict(self.last_refresh),
            "peers": {peer: health.to_dict() for peer, health in self.peers.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict, *, path: Path | None = None) -> "ControlSyncState":
        return cls(
            cursors={str(k): str(v) for k, v in dict(raw.get("cursors", {})).items()},
            last_refresh={str(k): float(v) for k, v in dict(raw.get("last_refresh", {})).items()},
            peers={
                str(k): PeerSyncHealth.from_dict(dict(v))
                for k, v in dict(raw.get("peers", {})).items()
            },
            path=path,
        )

    @classmethod
    def load(cls, path: str | Path) -> "ControlSyncState":
        p = Path(path)
        if not p.is_file():
            return cls(path=p)
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")), path=p)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)
