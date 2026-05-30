"""JSON-framed wire node runtime shared by daemons and the UDP harness."""

from __future__ import annotations

import base64
import json
import signal
import socket
import time
from os import urandom
from typing import Literal, Sequence

from sphinxmix.OutfoxNode import (
    circuit_packet_create,
    circuit_packet_process,
    outfox_process,
)
from sphinxmix.OutfoxParams import OutfoxParams, derive_circuit_key

from .config import ClusterConfig
from .envelope import PromptRequestEnvelope
from .provider import ProviderError, expert_reply_chunks


ROUTE_MAGIC = b"POR1"
NODE_ID_SIZE = 16
CIRCUIT_ID_SIZE = 16
KEY_SIZE = 16

NodeRole = Literal["relay", "expert", "any"]


class WireNodeRuntime:
    def __init__(
        self,
        cluster: ClusterConfig,
        node_id: str,
        *,
        role: NodeRole | None = None,
    ):
        self.cluster = cluster
        self.node_id = node_id
        self.identity = cluster.node(node_id)
        self.role: NodeRole = role or self.identity.role  # type: ignore[assignment]
        if self.role not in {"relay", "expert", "any"}:
            self.role = "any"
        params = cluster.params
        self.params = OutfoxParams(
            payload_size=params.payload_size,
            routing_size=params.routing_size,
            max_hops=params.max_hops,
        )
        self.sk = bytes.fromhex(self.identity.kem_sk_hex)
        self.pk = bytes.fromhex(self.identity.kem_pk_hex)
        self.circuits: dict[str, dict[str, object]] = {}
        self._harness = cluster.to_harness_dict()
        self._shutdown = False

    def install_signal_handlers(self) -> None:
        def _handle(_signum, _frame):
            self._shutdown = True

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)

    def serve_forever(self) -> int:
        self.install_signal_handlers()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.identity.host, self.identity.port))
        sock.settimeout(0.5)
        print(
            f"node={self.node_id} event=started role={self.role} "
            f"addr={self.identity.host}:{self.identity.port}",
            flush=True,
        )
        while not self._shutdown:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            frame = json.loads(data.decode("utf-8"))
            kind = frame.get("kind")
            if kind == "shutdown":
                print(f"node={self.node_id} event=shutdown", flush=True)
                return 0
            if kind == "forward":
                self._handle_forward(sock, frame)
            elif kind == "circuit":
                self._handle_circuit(sock, frame)
        print(f"node={self.node_id} event=stopped signal=yes", flush=True)
        return 0

    def _handle_forward(self, sock: socket.socket, frame: dict) -> None:
        header = _b64d(frame["header"])
        payload = _b64d(frame["payload"])

        circuit_installed = {}
        def _on_circuit(inbound_cid, circuit_key, next_hop, outbound_cid, ttl):
            cid_hex = inbound_cid.hex()
            out_hex = outbound_cid.hex()
            nh = next_hop.rstrip(b'\x00').decode('ascii', errors='replace')
            self.circuits[cid_hex] = {
                "key": circuit_key.hex(),
                "outbound_cid": out_hex,
                "next_id": nh,
                "high_watermark": -1,
                "last_active": time.time(),
            }
            circuit_installed["inbound_cid"] = cid_hex
            circuit_installed["return_next"] = nh

        try:
            hop_result = outfox_process(
                self.params, self.sk, self.pk, (header, payload),
                is_last=False, on_circuit=_on_circuit)
        except ValueError as exc:
            print(f"node={self.node_id} event=forward_rejected reason={exc}", flush=True)
            return

        if hop_result is None:
            print(f"node={self.node_id} event=forward_expired_or_invalid", flush=True)
            return

        routing_info, _flag, next_packet = hop_result
        por1_instr = None
        if routing_info[: len(ROUTE_MAGIC)] == ROUTE_MAGIC:
            por1_instr = _unpack_route_info(routing_info, self.params.routing_size)
            _install_circuit(self.circuits, por1_instr, self.node_id)

        if por1_instr is not None:
            next_id = por1_instr["next_forward"]
            cid_log = por1_instr["inbound_cid"][:8]
            return_next = por1_instr["return_next"]
        else:
            next_id = routing_info.rstrip(b'\x00').decode('ascii', errors='replace')
            cid_log = circuit_installed.get("inbound_cid", "")[:8]
            return_next = circuit_installed.get("return_next", "")

        next_header, next_payload = next_packet

        if next_id and next_header:
            print(
                f"node={self.node_id} event=forward_hop next={next_id} "
                f"link_cid={cid_log} return_next={return_next} prompt_visible=no",
                flush=True,
            )
            _send_frame(sock, self._harness, next_id, {
                "kind": "forward",
                "header": _b64e(next_header),
                "payload": _b64e(next_payload),
            })
            return

        if self.role == "relay":
            print(f"node={self.node_id} event=forward_exit_disallowed role=relay", flush=True)
            return

        final_result = outfox_process(
            self.params, self.sk, self.pk, (header, payload),
            is_last=True, on_circuit=_on_circuit)
        if final_result is None:
            print(f"node={self.node_id} event=exit_rejected", flush=True)
            return

        _routing, _flag, msg, _surb_info = final_result
        envelope = PromptRequestEnvelope.from_json(msg)
        prompt = envelope.prompt_text()
        expertise = envelope.intent_descriptor.get("requested_expertise") or "auto"
        degraded = bool(envelope.intent_descriptor.get("degraded_anonymity"))
        if por1_instr is not None:
            exit_cid = por1_instr["inbound_cid"]
            return_next = por1_instr["return_next"]
        else:
            exit_cid = circuit_installed.get("inbound_cid", "")
            return_next = circuit_installed.get("return_next", "")
        exit_entry = self.circuits.get(exit_cid)
        if exit_entry is None:
            print(
                f"node={self.node_id} event=exit_missing_circuit "
                f"link_cid={exit_cid[:8]}",
                flush=True,
            )
            return
        exit_key = bytes.fromhex(exit_entry["key"])
        exit_outbound = bytes.fromhex(exit_entry["outbound_cid"])

        print(
            "node={node} event=expert_exit selected=yes prompt_visible=yes "
            "expertise={expertise!r} return_next={return_next} link_cid={cid} "
            "degraded={degraded}".format(
                node=self.node_id,
                expertise=expertise,
                return_next=return_next or exit_entry["next_id"],
                cid=exit_cid[:8],
                degraded=str(degraded).lower(),
            ),
            flush=True,
        )
        try:
            chunks = expert_reply_chunks(envelope, self.node_id)
        except ProviderError as exc:
            print(
                f"node={self.node_id} event=provider_error retryable={str(exc.retryable).lower()} "
                f"reason={exc!s}",
                flush=True,
            )
            chunks = [
                f"[provider_error] peer={self.node_id} status={exc.status} message={exc}"
            ]

        for seq, chunk in enumerate(chunks):
            plain = json.dumps({"seq": seq, "data": chunk, "done": False}).encode("utf-8")
            _stream_return_chunk(
                sock,
                self._harness,
                self.params,
                exit_entry["next_id"],
                exit_outbound,
                seq,
                plain,
                exit_key,
            )
            time.sleep(0.05)

        done_seq = len(chunks)
        done = json.dumps({"seq": done_seq, "data": "", "done": True}).encode("utf-8")
        _stream_return_chunk(
            sock,
            self._harness,
            self.params,
            exit_entry["next_id"],
            exit_outbound,
            done_seq,
            done,
            exit_key,
        )

    def _handle_circuit(self, sock: socket.socket, frame: dict) -> None:
        packet = _b64d(frame["packet"])
        inbound_cid = packet[1:17].hex()
        nonce = int.from_bytes(packet[17:25], "big")
        entry = self.circuits.get(inbound_cid)
        seq = frame.get("seq", -1)

        if entry is None:
            print(
                f"node={self.node_id} event=circuit_missing link_cid={inbound_cid[:8]} seq={seq}",
                flush=True,
            )
            return
        if nonce <= int(entry.get("high_watermark", -1)):
            print(
                f"node={self.node_id} event=circuit_replay link_cid={inbound_cid[:8]} seq={seq}",
                flush=True,
            )
            return
        entry["high_watermark"] = nonce

        key = bytes.fromhex(entry["key"])
        outbound_cid = bytes.fromhex(entry["outbound_cid"])
        next_id = entry["next_id"]
        processed = circuit_packet_process(
            self.params, key, packet, outbound_link_cid=outbound_cid
        )
        if processed is None:
            print(
                f"node={self.node_id} event=circuit_malformed link_cid={inbound_cid[:8]} seq={seq}",
                flush=True,
            )
            return
        _inbound, _nonce, forwarded = processed
        print(
            f"node={self.node_id} event=circuit_hop link_cid={inbound_cid[:8]} seq={seq} "
            f"next={next_id} payload_visible=no",
            flush=True,
        )
        _send_frame(sock, self._harness, next_id, {
            "kind": "circuit",
            "seq": seq,
            "packet": _b64e(forwarded),
        })


def pack_route_info(next_forward, return_next, inbound_cid, key_seed, outbound_cid, routing_size):
    raw = (
        ROUTE_MAGIC
        + _fixed_id(next_forward)
        + _fixed_id(return_next)
        + inbound_cid
        + key_seed
        + outbound_cid
    )
    return raw + (b"\x00" * (routing_size - len(raw)))


def build_native_forward_plan(forward_path: Sequence[str] | list[str] | tuple[str, ...]):
    """Build route-info and circuit setup for process-wire clients.

    The visible routing field carries only the next forward hop. Return circuit
    state is carried in Outfox circuit setup fields and installed by relay
    callbacks.
    """

    if not forward_path:
        raise ValueError("forward_path is required")

    n = len(forward_path)
    client_inbound = urandom(CIRCUIT_ID_SIZE)
    inbound_cids = [urandom(CIRCUIT_ID_SIZE) for _ in range(n)]
    outbound_cids = [client_inbound] + inbound_cids[:-1]
    seeds = [urandom(KEY_SIZE) for _ in range(n)]
    keys = [derive_circuit_key(seeds[i], inbound_cids[i]) for i in range(n)]

    route_infos: list[bytes] = []
    circuit_setup: list[dict[str, object]] = []
    for index, _node_id in enumerate(forward_path):
        next_forward = forward_path[index + 1] if index + 1 < n else ""
        return_next = "client" if index == 0 else forward_path[index - 1]
        route_infos.append(next_forward.encode("ascii"))
        circuit_setup.append(
            {
                "inbound_link_cid": inbound_cids[index],
                "key_seed": seeds[index],
                "next_hop": return_next.encode("ascii"),
                "outbound_link_cid": outbound_cids[index],
                "ttl": 120,
            }
        )

    return route_infos, circuit_setup, list(reversed(keys))


def build_por1_forward_plan(
    forward_path: Sequence[str],
    *,
    selected_peer_id: str,
    routing_size: int,
):
    """Legacy harness plan: circuit state embedded in POR1 routing_info blobs.

    Kept during migration so clients that still pack setup in route info work
    against runtimes that prefer native Outfox circuit callbacks.
    """

    if not forward_path:
        raise ValueError("forward_path is required")

    n = len(forward_path)
    client_inbound = urandom(CIRCUIT_ID_SIZE)
    inbound_cids = [urandom(CIRCUIT_ID_SIZE) for _ in range(n)]
    outbound_cids = [client_inbound] + inbound_cids[:-1]
    seeds = [urandom(KEY_SIZE) for _ in range(n)]
    keys = [derive_circuit_key(seeds[i], inbound_cids[i]) for i in range(n)]

    route_infos: list[bytes] = []
    for index, fwd_node_id in enumerate(forward_path):
        next_forward = forward_path[index + 1] if index + 1 < n else ""
        if fwd_node_id == selected_peer_id:
            return_next = (
                list(reversed(forward_path[:-1]))[0]
                if len(forward_path) > 1
                else "client"
            )
        else:
            return_relays = list(reversed(forward_path[:-1]))
            pos = return_relays.index(fwd_node_id)
            return_next = (
                "client" if pos + 1 == len(return_relays) else return_relays[pos + 1]
            )
        route_infos.append(
            pack_route_info(
                next_forward,
                return_next,
                inbound_cids[index],
                seeds[index],
                outbound_cids[index],
                routing_size,
            )
        )

    return route_infos, list(reversed(keys))


def _unpack_route_info(data, routing_size):
    data = bytes(data)
    if data[:4] != ROUTE_MAGIC:
        raise ValueError("bad route info magic")
    offset = 4
    next_forward = _read_fixed_id(data[offset : offset + NODE_ID_SIZE])
    offset += NODE_ID_SIZE
    return_next = _read_fixed_id(data[offset : offset + NODE_ID_SIZE])
    offset += NODE_ID_SIZE
    inbound_cid = data[offset : offset + CIRCUIT_ID_SIZE]
    offset += CIRCUIT_ID_SIZE
    key_seed = data[offset : offset + KEY_SIZE]
    offset += KEY_SIZE
    outbound_cid = data[offset : offset + CIRCUIT_ID_SIZE]
    circuit_key = derive_circuit_key(key_seed, inbound_cid)
    return {
        "next_forward": next_forward,
        "return_next": return_next,
        "inbound_cid": inbound_cid.hex(),
        "outbound_cid": outbound_cid.hex(),
        "key": circuit_key.hex(),
    }


def _install_circuit(circuits, instr, node_id: str):
    if not instr["return_next"] or instr["return_next"] == node_id:
        return
    circuits[instr["inbound_cid"]] = {
        "key": instr["key"],
        "outbound_cid": instr["outbound_cid"],
        "next_id": instr["return_next"],
        "high_watermark": -1,
        "last_active": time.time(),
    }


def _stream_return_chunk(sock, harness, params, next_id, outbound_cid, seq, plaintext, exit_key):
    packet = circuit_packet_create(params, outbound_cid, seq, plaintext, [exit_key])
    _send_frame(sock, harness, next_id, {
        "kind": "circuit",
        "seq": seq,
        "packet": _b64e(packet),
    })


def _send_frame(sock, harness: dict, target_id: str, frame: dict) -> None:
    if target_id == "client":
        target = harness["client"]
    else:
        target = harness["nodes"][target_id]
    sock.sendto(json.dumps(frame).encode("utf-8"), (target["host"], target["port"]))


def _fixed_id(value: str) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > NODE_ID_SIZE:
        raise ValueError(f"node id too long: {value}")
    return encoded + (b"\x00" * (NODE_ID_SIZE - len(encoded)))


def _read_fixed_id(data: bytes) -> str:
    return data.rstrip(b"\x00").decode("ascii")


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))
