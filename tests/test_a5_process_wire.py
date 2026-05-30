"""A5 process-wire exit test: binary datagrams across separate node processes.

Proves the production binary wire path works end-to-end:
  - por-relay and por-expert spawned as subprocesses
  - Client sends 0x00-prefixed forward packet via raw UDP
  - Relays install circuits via on_circuit callback
  - Expert decrypts envelope, streams circuit packets back
  - Client receives 0x01 circuit packets, decrypts tokens
  - No JSON frames, no base64, no MixnetSim, no demo modules
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from sphinxmix.OutfoxClient import packet_create
from sphinxmix.OutfoxNode import circuit_packet_decrypt
from sphinxmix.OutfoxParams import OutfoxParams

from por.config import ClusterConfig
from por.envelope import PromptRequestEnvelope
from por.expert_mode import ExpertModeConfig, prepare_expert_mode_request
from por.expert_route import PeerObservation, RouteIntent
from por.directory import PublicManifestDirectory
from por.memory_index import IndexConfig, build_memory_index
from por.node_runtime import build_native_forward_plan
from por.wire_frame import encode_forward, encode_shutdown, decode_datagram


def _reserve_ports(count):
    socks = []
    try:
        for _ in range(count):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", 0))
            socks.append(s)
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def test_a5_binary_wire_process():
    """Binary wire: relay + expert subprocesses, raw UDP, no JSON."""
    with tempfile.TemporaryDirectory(prefix="por-a5-wire-") as tmp:
        tmp_path = Path(tmp)
        payload_size = 4096
        routing_size = 16
        params = OutfoxParams(payload_size=payload_size, routing_size=routing_size, max_hops=5)

        ports = _reserve_ports(4)
        node_ids = ["relay1", "relay2", "expert_art"]
        nodes = {}
        for nid, port in zip(node_ids, ports[:3]):
            pk, sk = params.kem.keygen()
            role = "expert" if nid.startswith("expert") else "relay"
            nodes[nid] = {
                "host": "127.0.0.1", "port": port,
                "kem_pk": pk.hex(), "kem_sk": sk.hex(), "role": role,
            }

        config = {
            "params": {"payload_size": payload_size, "routing_size": routing_size, "max_hops": 5},
            "client": {"host": "127.0.0.1", "port": ports[3]},
            "nodes": nodes,
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        # Start node processes with binary wire
        procs = []
        for nid in node_ids:
            role = "expert" if nid.startswith("expert") else "relay"
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "por", role, "--config", str(config_path), "--node-id", nid],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            ))
        time.sleep(0.5)

        try:
            # Build envelope
            art_dir = tmp_path / "art_mem"
            art_dir.mkdir()
            (art_dir / "art.md").write_text("Monet Impressionism light color painting", encoding="utf-8")
            art_manifest = build_memory_index(IndexConfig(peer_id="expert_art", roots=(str(art_dir),))).manifest
            directory = PublicManifestDirectory.from_manifests(
                (art_manifest,),
                (PeerObservation(peer_id="expert_art", p50_latency_ms=80),),
                source="a5-wire",
            )
            prepared = prepare_expert_mode_request(
                RouteIntent(prompt="What did Monet change?", requested_expertise="art", random_seed=1),
                directory,
                ExpertModeConfig(min_pool_size=1, allow_degraded_pool=True),
            )

            forward_path = ["relay1", "relay2", "expert_art"]
            route_infos, circuit_setup, client_peel_keys = build_native_forward_plan(tuple(forward_path))
            kem_keys = [bytes.fromhex(nodes[nid]["kem_pk"]) for nid in forward_path]

            envelope = prepared.envelope
            if envelope is None:
                envelope = PromptRequestEnvelope.visible_prompt(
                    prompt="What did Monet change?",
                    selected_peer_id="expert_art",
                    requested_expertise="art",
                )

            header, payload = packet_create(
                params, route_infos, kem_keys,
                envelope.to_json().encode("utf-8"),
                circuit_setup=circuit_setup,
            )

            # Send binary forward packet
            client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client_sock.bind(("127.0.0.1", ports[3]))
            client_sock.settimeout(0.5)

            send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            send_sock.sendto(encode_forward(header, payload), ("127.0.0.1", ports[0]))

            # Receive binary circuit packets
            chunks = []
            deadline = time.time() + 6.0
            while time.time() < deadline:
                try:
                    data, _ = client_sock.recvfrom(65535)
                except socket.timeout:
                    continue
                kind, body, _ = decode_datagram(data, payload_size)
                if kind != "circuit":
                    continue
                plain = circuit_packet_decrypt(params, client_peel_keys, body)
                if plain is None:
                    continue
                chunk = json.loads(plain.decode("utf-8"))
                if chunk.get("done"):
                    break
                chunks.append(chunk["data"])

            client_sock.close()
            send_sock.close()

            response = "".join(chunks)
            assert len(response) > 0, "No response received through binary wire"

        finally:
            # Shutdown nodes with binary shutdown frame
            shutdown_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for nid in node_ids:
                shutdown_sock.sendto(encode_shutdown(), ("127.0.0.1", nodes[nid]["port"]))
            shutdown_sock.close()

            all_logs = []
            for proc in procs:
                try:
                    out, _ = proc.communicate(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    out, _ = proc.communicate(timeout=2.0)
                all_logs.append(out)

            node_logs = "".join(all_logs)

        # Verify log events
        assert "event=forward_hop" in node_logs, "Missing forward_hop in relay logs"
        assert "event=expert_exit" in node_logs, "Missing expert_exit in logs"
        assert "event=circuit_hop" in node_logs, "Missing circuit_hop in relay logs"
        assert "prompt_visible=yes" in node_logs, "Expert should see prompt"
        assert "wire=binary" in node_logs, "Nodes should report binary wire mode"

        # Relay nodes must NOT see prompt (only expert does)
        for line in node_logs.split("\n"):
            if "event=forward_hop" in line and "prompt_visible" in line:
                assert "prompt_visible=no" in line, f"Relay saw prompt: {line}"

    print(f"[PASS] A5 process-wire: binary 0x00/0x01, {len(chunks)} chunks, no JSON frames.")
