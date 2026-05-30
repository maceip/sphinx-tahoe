"""Supernode daemon — reachability relay + mix node on one UDP bind.

Demux order (per docs/supernode_threat_model.md):
  1. REACH_* control → PeerAddressRelay (register/challenge/confirm/heartbeat)
  2. Outfox 0x00/0x01/0x02 → WireNodeRuntime (mix processing)
  3. Known peer addr → opaque forward to registered peer
  4. Unknown → drop

Does NOT import envelope, provider, expert_route, or call outfox_process
on the forward path. Only moves opaque UDP bytes.
"""

from __future__ import annotations

import socket
import time
from os import urandom
from typing import Sequence

from por.config import ClusterConfig
from por.node_runtime import WireNodeRuntime
from por.peer_address import (
    PeerAddressRelay, UdpEndpoint, AddressExposurePolicy,
    REGISTRATION_TTL_SECONDS, HEARTBEAT_INTERVAL_SECONDS,
)
from por.reach_wire import (
    decode_reach_datagram, encode_challenge, encode_heartbeat,
    is_reach_datagram,
)
from por.supernode import SupernodeForwarder


class SupernodeDaemon:
    """Single UDP bind: REACH control + mix relay + opaque NAT forward."""

    def __init__(
        self,
        runtime: WireNodeRuntime,
        relay_secret: bytes | None = None,
        *,
        ttl: int = REGISTRATION_TTL_SECONDS,
    ):
        self.runtime = runtime
        self.relay = PeerAddressRelay(
            relay_id=runtime.node_id,
            relay_endpoint=UdpEndpoint(runtime.identity.host, runtime.identity.port),
            secret=relay_secret or urandom(32),
            ttl_seconds=ttl,
        )
        self.forwarder = SupernodeForwarder(self.relay, ttl=ttl)
        self._client_sessions: dict[str, tuple[str, int]] = {}
        self._sock: socket.socket | None = None
        self._last_purge = time.time()

        runtime.on_reach_control = self._handle_reach
        runtime.on_opaque_forward = self._handle_opaque

    def _handle_reach(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            action = decode_reach_datagram(data)
        except ValueError:
            return

        if action.kind == "register":
            challenge = self.relay.request_registration(
                peer_id=action.peer_id,
                observed_endpoint=UdpEndpoint(*addr),
            )
            resp = encode_challenge(
                challenge.relay_id,
                challenge.observed_endpoint,
                challenge.cookie,
                challenge.expires_at,
            )
            if self._sock:
                self._sock.sendto(resp, addr)

        elif action.kind == "confirm":
            from por.peer_address import AddressChallenge
            challenge = AddressChallenge(
                peer_id=action.peer_id,
                relay_id=self.runtime.node_id,
                observed_endpoint=UdpEndpoint(*addr),
                cookie=action.cookie,
                issued_at=time.time() - 5,
                expires_at=time.time() + 25,
            )
            try:
                record = self.relay.confirm_registration(
                    challenge,
                    supported_transports=action.transports,
                    address_policy=action.policy,
                )
                self.forwarder.register_peer(action.peer_id, addr)
                self.runtime._log("reach_registered", fields={"peer_id": action.peer_id})
            except ValueError as e:
                self.runtime._log("reach_confirm_failed",
                                  level="warning", fields={"reason": str(e)})

        elif action.kind == "heartbeat":
            ok = self.forwarder.heartbeat(action.peer_id, addr)
            if ok:
                self.relay.heartbeat(action.peer_id, observed_endpoint=UdpEndpoint(*addr))

    def _handle_opaque(self, data: bytes, addr: tuple[str, int]) -> None:
        peer_id = self.forwarder.lookup_peer_by_addr(addr)
        if peer_id is not None:
            session_key = f"{peer_id}:{addr[0]}:{addr[1]}"
            client_addr = self._client_sessions.get(session_key)
            if client_addr and self._sock:
                self._sock.sendto(data, client_addr)
                self.runtime._log("opaque_forward_return",
                                  fields={"peer_id": peer_id, "bytes": len(data)})
            return

        # Unknown source — try to forward to a registered peer
        # For now, drop. Transport team will add session/routing logic.
        self.runtime._log("opaque_forward_drop",
                          level="warning", fields={"bytes": len(data)})

    def attach_socket(self, sock: socket.socket) -> None:
        self._sock = sock

    def forward_to_peer(self, peer_id: str, data: bytes,
                        client_addr: tuple[str, int]) -> bool:
        peer_addr = self.forwarder.lookup_peer_addr(peer_id)
        if peer_addr is None or self._sock is None:
            return False
        self._sock.sendto(data, peer_addr)
        session_key = f"{peer_id}:{peer_addr[0]}:{peer_addr[1]}"
        self._client_sessions[session_key] = client_addr
        return True

    def purge_if_due(self, interval: float = 60.0) -> None:
        now = time.time()
        if now - self._last_purge >= interval:
            self.forwarder.purge_expired()
            self.relay.purge_expired()
            self._last_purge = now


def run_supernode(*, config_path: str, node_id: str, relay_secret: bytes | None = None) -> int:
    cluster = ClusterConfig.load(config_path)
    runtime = WireNodeRuntime(cluster, node_id, role="any")
    daemon = SupernodeDaemon(runtime, relay_secret=relay_secret)
    return runtime.serve_forever(binary_wire=True)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run a P-OR supernode (relay + reachability).")
    parser.add_argument("--config", required=True)
    parser.add_argument("--node-id", required=True)
    args = parser.parse_args(argv)
    return run_supernode(config_path=args.config, node_id=args.node_id)


if __name__ == "__main__":
    raise SystemExit(main())
