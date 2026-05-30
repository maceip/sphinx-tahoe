"""Local UDP demo for P-OR Expert Mode.

This is a demo harness, not the production transport. It uses real localhost UDP
datagrams and separate node processes so traces are grounded in process and
socket boundaries instead of direct function calls.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from sphinxmix.OutfoxClient import packet_create
from sphinxmix.OutfoxNode import (
    circuit_packet_create,
    circuit_packet_decrypt,
    circuit_packet_process,
    outfox_process,
)
from sphinxmix.OutfoxParams import OutfoxParams, derive_circuit_key

from .directory import PublicManifestDirectory
from .envelope import HYBRID_RETURN_PATH_V2, PromptRequestEnvelope
from .expert_mode import ExpertModeConfig, prepare_expert_mode_request
from .expert_route import PeerObservation, RouteIntent
from .memory_index import IndexConfig, build_memory_index


ROUTE_MAGIC = b"POR1"
NODE_ID_SIZE = 16
CIRCUIT_ID_SIZE = 16
KEY_SIZE = 16
ROUTE_INFO_SIZE = 96
DEFAULT_PAYLOAD_SIZE = 2048


@dataclass(frozen=True)
class DemoResult:
    selected_peer_id: str
    degraded_anonymity: bool
    fallback_used: bool
    response_text: str
    node_logs: str
    client_logs: str


def run_demo(node_count: int = 4, timeout: float = 8.0) -> DemoResult:
    if node_count < 3 or node_count > 5:
        raise ValueError("demo supports 3-5 local node processes")

    with tempfile.TemporaryDirectory(prefix="por-udp-demo-") as tmp:
        tmp_path = Path(tmp)
        params = OutfoxParams(payload_size=DEFAULT_PAYLOAD_SIZE, routing_size=ROUTE_INFO_SIZE, max_hops=5)
        node_ids = _node_ids(node_count)
        ports = _reserve_ports(len(node_ids) + 1)
        client_addr = ("127.0.0.1", ports[-1])

        nodes = {}
        for node_id, port in zip(node_ids, ports[:-1]):
            pk, sk = params.kem.keygen()
            nodes[node_id] = {
                "host": "127.0.0.1",
                "port": port,
                "kem_pk": pk.hex(),
                "kem_sk": sk.hex(),
            }

        config = {
            "params": {
                "payload_size": DEFAULT_PAYLOAD_SIZE,
                "routing_size": ROUTE_INFO_SIZE,
                "max_hops": 5,
            },
            "client": {"host": client_addr[0], "port": client_addr[1]},
            "nodes": nodes,
        }
        config_path = tmp_path / "demo_config.json"
        config_path.write_text(json.dumps(config, sort_keys=True, indent=2), encoding="utf-8")

        procs = _start_nodes(config_path, node_ids)
        try:
            time.sleep(0.35)
            selected_peer_id, degraded, fallback_used, prompt, expertise = _plan_demo_route(tmp_path)
            if selected_peer_id not in nodes:
                response_text = _frontier_fallback_response(prompt, "no selected expert peer")
                client_logs = (
                    "client event=expert_plan selected=none degraded_anonymity=false "
                    "fallback_used=true"
                )
                return DemoResult(
                    selected_peer_id="",
                    degraded_anonymity=degraded,
                    fallback_used=True,
                    response_text=response_text,
                    node_logs="",
                    client_logs=client_logs,
                )

            relay_path = [nid for nid in node_ids if nid.startswith("relay")][:2]
            forward_path = relay_path + [selected_peer_id]
            response_text, client_logs = _send_prompt_and_receive_stream(
                params=params,
                config=config,
                client_addr=client_addr,
                forward_path=forward_path,
                prompt=prompt,
                expertise=expertise,
                selected_peer_id=selected_peer_id,
                degraded_anonymity=degraded,
                timeout=timeout,
            )
        finally:
            _shutdown_nodes(config, node_ids)
            node_logs = _collect_node_logs(procs)

    return DemoResult(
        selected_peer_id=selected_peer_id,
        degraded_anonymity=degraded,
        fallback_used=fallback_used,
        response_text=response_text,
        node_logs=node_logs,
        client_logs=client_logs,
    )


def node_main(config_path: str, node_id: str) -> int:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    params_cfg = config["params"]
    params = OutfoxParams(
        payload_size=params_cfg["payload_size"],
        routing_size=params_cfg["routing_size"],
        max_hops=params_cfg["max_hops"],
    )
    node_cfg = config["nodes"][node_id]
    sk = bytes.fromhex(node_cfg["kem_sk"])
    pk = bytes.fromhex(node_cfg["kem_pk"])
    circuits: dict[str, dict[str, object]] = {}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((node_cfg["host"], node_cfg["port"]))
    sock.settimeout(0.5)
    print(f"node={node_id} event=started addr={node_cfg['host']}:{node_cfg['port']}", flush=True)

    while True:
        try:
            data, _addr = sock.recvfrom(65535)
        except socket.timeout:
            continue

        frame = json.loads(data.decode("utf-8"))
        kind = frame.get("kind")
        if kind == "shutdown":
            print(f"node={node_id} event=shutdown", flush=True)
            return 0
        if kind == "forward":
            _handle_forward(sock, config, params, node_id, sk, pk, circuits, frame)
        elif kind == "circuit":
            _handle_circuit(sock, config, params, node_id, circuits, frame)


def _handle_forward(sock, config, params, node_id, sk, pk, circuits, frame):
    header = _b64d(frame["header"])
    payload = _b64d(frame["payload"])
    try:
        hop_result = outfox_process(params, sk, pk, (header, payload), is_last=False)
    except ValueError as exc:
        print(f"node={node_id} event=forward_rejected reason={exc}", flush=True)
        return

    if hop_result is None:
        print(f"node={node_id} event=forward_expired_or_invalid", flush=True)
        return

    routing_info, _flag, next_packet = hop_result
    instr = _unpack_route_info(routing_info)
    _install_circuit(node_id, circuits, instr)

    next_header, next_payload = next_packet
    if next_header:
        print(
            "node={node} event=forward_hop next={next_id} link_cid={cid} "
            "return_next={return_next} prompt_visible=no".format(
                node=node_id,
                next_id=instr["next_forward"],
                cid=instr["inbound_cid"][:8],
                return_next=instr["return_next"],
            ),
            flush=True,
        )
        _send_frame(sock, config, instr["next_forward"], {
            "kind": "forward",
            "header": _b64e(next_header),
            "payload": _b64e(next_payload),
        })
        return

    final_result = outfox_process(params, sk, pk, (header, payload), is_last=True)
    if final_result is None:
        print(f"node={node_id} event=exit_rejected", flush=True)
        return

    _routing, _flag, msg, _surb_info = final_result
    envelope = PromptRequestEnvelope.from_json(msg)
    prompt = envelope.prompt_text()
    expertise = envelope.intent_descriptor.get("requested_expertise") or "auto"
    degraded = bool(envelope.intent_descriptor.get("degraded_anonymity"))
    exit_entry = circuits.get(instr["inbound_cid"])
    if exit_entry is None:
        print(f"node={node_id} event=exit_missing_circuit link_cid={instr['inbound_cid'][:8]}", flush=True)
        return
    exit_key = bytes.fromhex(exit_entry["key"])
    exit_outbound = bytes.fromhex(exit_entry["outbound_cid"])

    print(
        "node={node} event=expert_exit selected=yes prompt_visible=yes "
        "expertise={expertise!r} return_next={return_next} link_cid={cid} degraded={degraded}".format(
            node=node_id,
            expertise=expertise,
            return_next=instr["return_next"],
            cid=instr["inbound_cid"][:8],
            degraded=str(degraded).lower(),
        ),
        flush=True,
    )
    chunks = _response_chunks(node_id, prompt, expertise)
    for seq, chunk in enumerate(chunks):
        plain = json.dumps({"seq": seq, "data": chunk, "done": False}).encode("utf-8")
        _stream_return_chunk(sock, config, params, instr["return_next"], exit_outbound, seq, plain, exit_key)
        time.sleep(0.05)

    done_seq = len(chunks)
    done = json.dumps({"seq": done_seq, "data": "", "done": True}).encode("utf-8")
    _stream_return_chunk(sock, config, params, instr["return_next"], exit_outbound, done_seq, done, exit_key)


def _handle_circuit(sock, config, params, node_id, circuits, frame):
    packet = _b64d(frame["packet"])
    inbound_cid = packet[1:17].hex()
    nonce = int.from_bytes(packet[17:25], "big")
    entry = circuits.get(inbound_cid)
    seq = frame.get("seq", -1)

    if entry is None:
        print(f"node={node_id} event=circuit_missing link_cid={inbound_cid[:8]} seq={seq}", flush=True)
        return
    if nonce <= int(entry.get("high_watermark", -1)):
        print(f"node={node_id} event=circuit_replay link_cid={inbound_cid[:8]} seq={seq}", flush=True)
        return
    entry["high_watermark"] = nonce

    key = bytes.fromhex(entry["key"])
    outbound_cid = bytes.fromhex(entry["outbound_cid"])
    next_id = entry["next_id"]
    processed = circuit_packet_process(params, key, packet, outbound_link_cid=outbound_cid)
    if processed is None:
        print(f"node={node_id} event=circuit_malformed link_cid={inbound_cid[:8]} seq={seq}", flush=True)
        return
    _inbound, _nonce, forwarded = processed
    print(
        f"node={node_id} event=circuit_hop link_cid={inbound_cid[:8]} seq={seq} "
        f"next={next_id} payload_visible=no",
        flush=True,
    )
    _send_frame(sock, config, next_id, {
        "kind": "circuit",
        "seq": seq,
        "packet": _b64e(forwarded),
    })


def _stream_return_chunk(sock, config, params, next_id, outbound_cid, seq, plaintext, exit_key):
    packet = circuit_packet_create(params, outbound_cid, seq, plaintext, [exit_key])
    _send_frame(sock, config, next_id, {
        "kind": "circuit",
        "seq": seq,
        "packet": _b64e(packet),
    })


def _send_prompt_and_receive_stream(
    params,
    config,
    client_addr,
    forward_path,
    prompt,
    expertise,
    selected_peer_id,
    degraded_anonymity,
    timeout,
):
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_sock.bind(client_addr)
    client_sock.settimeout(0.5)

    n = len(forward_path)
    client_inbound = os.urandom(CIRCUIT_ID_SIZE)
    inbound_cids = [os.urandom(CIRCUIT_ID_SIZE) for _ in range(n)]
    outbound_cids = [None] * n
    seeds = [os.urandom(KEY_SIZE) for _ in range(n)]

    # Link binding: forward_path[0].outbound = client_inbound
    # forward_path[i].outbound = forward_path[i-1].inbound
    outbound_cids[0] = client_inbound
    for i in range(1, n):
        outbound_cids[i] = inbound_cids[i - 1]

    keys = [derive_circuit_key(seeds[i], inbound_cids[i]) for i in range(n)]

    route_infos = []
    for index, fwd_node_id in enumerate(forward_path):
        next_forward = forward_path[index + 1] if index + 1 < len(forward_path) else ""
        if fwd_node_id == selected_peer_id:
            return_next = list(reversed(forward_path[:-1]))[0] if len(forward_path) > 1 else "client"
        else:
            return_relays = list(reversed(forward_path[:-1]))
            pos = return_relays.index(fwd_node_id)
            return_next = "client" if pos + 1 == len(return_relays) else return_relays[pos + 1]
        route_infos.append(_pack_route_info(
            next_forward, return_next,
            inbound_cids[index], seeds[index], outbound_cids[index]))

    # Client peels: outermost relay first, then toward exit, then exit key last
    client_peel_keys = list(reversed(keys))
    from sphinxmix.ta_claims import streaming_return_descriptor

    app = PromptRequestEnvelope.visible_prompt(
        prompt=prompt,
        selected_peer_id=selected_peer_id,
        requested_expertise=expertise,
        provider_request={
            "provider": "expert_peer",
            "selected_peer_id": selected_peer_id,
            "fallback_provider": "frontier",
            "stream": True,
            "harness_provider_call": False,
        },
        return_descriptor=streaming_return_descriptor(
            mode=HYBRID_RETURN_PATH_V2,
            paced=False,
            extra={
                "return_profile": "relay_additive_link_cid",
            },
        ),
        privacy_warnings=(
            "candidate pool below privacy target; destination anonymity degraded",
        ) if degraded_anonymity else (),
        extra_intent={"degraded_anonymity": degraded_anonymity},
    )
    keys = [bytes.fromhex(config["nodes"][node_id]["kem_pk"]) for node_id in forward_path]
    header, payload = packet_create(params, route_infos, keys, app.to_json().encode("utf-8"))

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _send_frame(send_sock, config, forward_path[0], {
        "kind": "forward",
        "header": _b64e(header),
        "payload": _b64e(payload),
    })

    chunks = []
    logs = [
        f"client event=expert_plan selected={selected_peer_id} "
        f"degraded_anonymity={str(degraded_anonymity).lower()} forward_path={'/'.join(forward_path)}",
    ]
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, _addr = client_sock.recvfrom(65535)
        except socket.timeout:
            continue
        frame = json.loads(data.decode("utf-8"))
        if frame.get("kind") != "circuit":
            continue
        plain = circuit_packet_decrypt(params, client_peel_keys, _b64d(frame["packet"]))
        if plain is None:
            logs.append("client event=stream_corrupt")
            continue
        chunk = json.loads(plain.decode("utf-8"))
        logs.append(f"client event=stream_chunk seq={chunk['seq']} bytes={len(chunk['data'])}")
        if chunk.get("done"):
            break
        chunks.append(chunk["data"])
    else:
        raise TimeoutError("timed out waiting for streamed return path")

    client_sock.close()
    send_sock.close()
    return "".join(chunks), "\n".join(logs)


def _plan_demo_route(tmp_path: Path):
    art_root = tmp_path / "expert_art_memory"
    sys_root = tmp_path / "expert_sys_memory"
    art_root.mkdir()
    sys_root.mkdir()
    (art_root / "impressionism.md").write_text(
        "Monet Degas Renoir Impressionism Paris Salon color light brushwork modern painting.",
        encoding="utf-8",
    )
    (sys_root / "systems.md").write_text(
        "QUIC UDP congestion control packet loss stream transport scheduler.",
        encoding="utf-8",
    )
    art_manifest = build_memory_index(IndexConfig(peer_id="expert_art", roots=(str(art_root),))).manifest
    sys_manifest = build_memory_index(IndexConfig(peer_id="expert_sys", roots=(str(sys_root),))).manifest
    prompt = "What did Monet change about modern painting?"
    expertise = "Impressionist art history"
    directory = PublicManifestDirectory.from_manifests(
        (art_manifest, sys_manifest),
        (
            PeerObservation(peer_id="expert_art", p50_latency_ms=80, completion_rate=0.99),
            PeerObservation(peer_id="expert_sys", p50_latency_ms=60, completion_rate=0.99),
        ),
        source="udp-demo",
    )
    prepared = prepare_expert_mode_request(
        RouteIntent(
            prompt=prompt,
            requested_expertise=expertise,
            random_seed=3,
        ),
        directory,
        ExpertModeConfig(min_pool_size=3, allow_degraded_pool=True),
    )
    fallback = prepare_expert_mode_request(
        RouteIntent(
            prompt="Explain basalt petrology",
            requested_expertise="basalt petrology",
            fallback_provider="frontier",
        ),
        directory,
    )
    plan = prepared.plan
    print(
        f"demo event=expert_selection use_expert={str(plan.use_expert).lower()} "
        f"selected={plan.selected_peer_id} degraded={str(plan.pool.degraded_anonymity).lower()} "
        f"pool_size={len(plan.pool.candidates)}",
        flush=True,
    )
    print(
        f"demo event=fallback_case use_expert={str(fallback.use_expert).lower()} "
        f"fallback_provider={fallback.plan.fallback_provider} reason={fallback.plan.reason!r}",
        flush=True,
    )
    return plan.selected_peer_id or "", plan.pool.degraded_anonymity, not plan.use_expert, prompt, expertise


def _pack_route_info(next_forward, return_next, inbound_cid, key_seed, outbound_cid):
    raw = (
        ROUTE_MAGIC
        + _fixed_id(next_forward)
        + _fixed_id(return_next)
        + inbound_cid
        + key_seed
        + outbound_cid
    )
    return raw + (b"\x00" * (ROUTE_INFO_SIZE - len(raw)))


def _unpack_route_info(data):
    data = bytes(data)
    if data[:4] != ROUTE_MAGIC:
        raise ValueError("bad route info magic")
    offset = 4
    next_forward = _read_fixed_id(data[offset:offset + NODE_ID_SIZE]); offset += NODE_ID_SIZE
    return_next = _read_fixed_id(data[offset:offset + NODE_ID_SIZE]); offset += NODE_ID_SIZE
    inbound_cid = data[offset:offset + CIRCUIT_ID_SIZE]; offset += CIRCUIT_ID_SIZE
    key_seed = data[offset:offset + KEY_SIZE]; offset += KEY_SIZE
    outbound_cid = data[offset:offset + CIRCUIT_ID_SIZE]; offset += CIRCUIT_ID_SIZE
    circuit_key = derive_circuit_key(key_seed, inbound_cid)
    return {
        "next_forward": next_forward,
        "return_next": return_next,
        "inbound_cid": inbound_cid.hex(),
        "outbound_cid": outbound_cid.hex(),
        "key": circuit_key.hex(),
    }


def _install_circuit(node_id, circuits, instr):
    if not instr["return_next"] or instr["return_next"] == node_id:
        return
    circuits[instr["inbound_cid"]] = {
        "key": instr["key"],
        "outbound_cid": instr["outbound_cid"],
        "next_id": instr["return_next"],
        "high_watermark": -1,
        "last_active": time.time(),
    }


def _fixed_id(value: str) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > NODE_ID_SIZE:
        raise ValueError(f"node id too long: {value}")
    return encoded + (b"\x00" * (NODE_ID_SIZE - len(encoded)))


def _read_fixed_id(data: bytes) -> str:
    return data.rstrip(b"\x00").decode("ascii")


def _node_ids(node_count: int) -> list[str]:
    base = ["relay1", "relay2", "expert_art", "expert_sys", "relay3"]
    return base[:node_count]


def _reserve_ports(count: int) -> list[int]:
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def _start_nodes(config_path: Path, node_ids: Sequence[str]) -> list[subprocess.Popen]:
    procs = []
    for node_id in node_ids:
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "por.udp_demo", "node", "--config", str(config_path), "--node-id", node_id],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        )
    return procs


def _shutdown_nodes(config: dict, node_ids: Sequence[str]) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    frame = json.dumps({"kind": "shutdown"}).encode("utf-8")
    for node_id in node_ids:
        node = config["nodes"][node_id]
        sock.sendto(frame, (node["host"], node["port"]))
    sock.close()


def _collect_node_logs(procs: Sequence[subprocess.Popen]) -> str:
    chunks = []
    for proc in procs:
        try:
            out, _ = proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.terminate()
            out, _ = proc.communicate(timeout=2.0)
        chunks.append(out)
    return "".join(chunks)


def _send_frame(sock, config: dict, target_id: str, frame: dict) -> None:
    if target_id == "client":
        target = config["client"]
    else:
        target = config["nodes"][target_id]
    sock.sendto(json.dumps(frame).encode("utf-8"), (target["host"], target["port"]))


def _response_chunks(node_id: str, prompt: str, expertise: str) -> list[str]:
    return [_harness_expert_response(node_id, prompt, expertise)]


def _harness_expert_response(node_id: str, prompt: str, expertise: str) -> str:
    return (
        f"[wire-harness expert_reply] peer={node_id} expertise={expertise!r} "
        f"prompt_len={len(prompt)} llm_called=no"
    )


def _frontier_fallback_response(prompt: str, reason: str) -> str:
    return (
        f"[wire-harness frontier_fallback] prompt_len={len(prompt)} "
        f"expert_used=no reason={reason}"
    )


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local UDP P-OR demo.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("demo")
    node = sub.add_parser("node")
    node.add_argument("--config", required=True)
    node.add_argument("--node-id", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.cmd == "node":
        return node_main(args.config, args.node_id)

    result = run_demo()
    print("demo event=response_begin")
    print(result.response_text)
    print("demo event=response_end")
    print("demo event=client_logs_begin")
    print(result.client_logs)
    print("demo event=client_logs_end")
    print("demo event=node_logs_begin")
    print(result.node_logs, end="")
    print("demo event=node_logs_end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
