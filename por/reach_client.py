"""REACH client: register an expert with a public reachability relay (item 12)."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .reach_wire import (
    REACH_CHALLENGE,
    decode_reach_datagram,
    encode_confirm,
    encode_heartbeat,
    encode_register,
)


@dataclass(frozen=True)
class ReachRelayEndpoint:
    host: str
    port: int


def register_with_relay(
    sock: socket.socket,
    relay: ReachRelayEndpoint,
    peer_id: str,
    *,
    timeout: float = 5.0,
) -> None:
    """Complete REACH register → challenge → confirm for ``peer_id``."""
    addr = (relay.host, relay.port)
    try:
        sock.bind(("0.0.0.0", 0))
    except OSError:
        pass
    sock.sendto(encode_register(peer_id), addr)
    deadline = time.time() + timeout
    cookie = None
    while time.time() < deadline:
        try:
            data, _source = sock.recvfrom(65535)
        except socket.timeout:
            continue
        if not data or data[:1] != REACH_CHALLENGE:
            continue
        action = decode_reach_datagram(data)
        cookie = action.cookie
        break
    if cookie is None:
        raise TimeoutError(f"REACH challenge not received from {relay.host}:{relay.port}")
    sock.sendto(encode_confirm(peer_id, cookie), addr)


def heartbeat_once(
    sock: socket.socket,
    relay: ReachRelayEndpoint,
    peer_id: str,
) -> None:
    sock.sendto(encode_heartbeat(peer_id), (relay.host, relay.port))


class ReachHeartbeatThread:
    """Background REACH heartbeats for a registered expert."""

    def __init__(
        self,
        sock: socket.socket,
        relay: ReachRelayEndpoint,
        peer_id: str,
        *,
        interval_seconds: float = 300.0,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._sock = sock
        self._relay = relay
        self._peer_id = peer_id
        self._interval = interval_seconds
        self._log = log or (lambda _msg: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="reach-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                heartbeat_once(self._sock, self._relay, self._peer_id)
                self._log(f"reach_heartbeat ok peer_id={self._peer_id[:16]}")
            except OSError as exc:
                self._log(f"reach_heartbeat failed: {exc}")
