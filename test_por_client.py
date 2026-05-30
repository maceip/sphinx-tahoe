import json
import subprocess
import sys
import time
from pathlib import Path

from sphinxmix.OutfoxParams import OutfoxParams

from por.client import run_client_once
from por.config import ClusterConfig, DEFAULT_PAYLOAD_SIZE, DEFAULT_ROUTING_SIZE
from por.directory import PublicManifestDirectory
from por.udp_demo import (
    _collect_node_logs,
    _demo_directory,
    _node_ids,
    _reserve_ports,
    _shutdown_nodes,
    _start_nodes,
)


def test_client_fallback_does_not_touch_wire(tmp_path):
    config_path, _harness, _node_ids = _write_cluster(tmp_path, node_count=3)
    cluster = ClusterConfig.load(config_path)

    result = run_client_once(
        cluster=cluster,
        discovery_provider=PublicManifestDirectory(records=tuple()),
        prompt="Explain basalt petrology.",
        requested_expertise="basalt petrology",
        relay_path=("relay1", "relay2"),
        timeout=0.5,
    )

    assert result.fallback_used is True
    assert result.selected_peer_id is None
    assert "frontier_fallback" in result.response_text
    assert "event=send_prepared_envelope" not in result.client_logs


def test_por_client_daemon_streams_over_process_nodes(tmp_path):
    config_path, harness, node_ids = _write_cluster(tmp_path, node_count=4)
    directory_path = tmp_path / "directory-snapshot.json"
    _demo_directory(tmp_path).save_snapshot(directory_path)

    procs = _start_nodes(config_path, node_ids)
    try:
        time.sleep(0.35)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "por.daemon.client",
                "--config",
                str(config_path),
                "--directory-snapshot",
                str(directory_path),
                "--prompt",
                "What did Monet change about modern painting?",
                "--expertise",
                "Impressionist art history",
                "--relay",
                "relay1",
                "--relay",
                "relay2",
                "--timeout",
                "8",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=12,
        )
    finally:
        _shutdown_nodes(harness, node_ids)
        node_logs = _collect_node_logs(procs)

    assert proc.returncode == 0, proc.stdout + "\n" + node_logs
    assert "[wire-harness expert_reply]" in proc.stdout
    assert "client event=response_begin" in proc.stdout
    assert "client event=stream_chunk" in proc.stdout
    assert "event=forward_hop" in node_logs
    assert "event=expert_exit" in node_logs
    assert "prompt_visible=no" in node_logs
    assert "prompt_visible=yes" in node_logs


def _write_cluster(tmp_path: Path, *, node_count: int):
    params = OutfoxParams(
        payload_size=DEFAULT_PAYLOAD_SIZE,
        routing_size=DEFAULT_ROUTING_SIZE,
        max_hops=5,
    )
    node_ids = _node_ids(node_count)
    ports = _reserve_ports(len(node_ids) + 1)
    nodes = {}
    for node_id, port in zip(node_ids, ports[:-1]):
        pk, sk = params.kem.keygen()
        nodes[node_id] = {
            "host": "127.0.0.1",
            "port": port,
            "kem_pk": pk.hex(),
            "kem_sk": sk.hex(),
            "role": "expert" if node_id.startswith("expert") else "relay",
        }
    harness = {
        "params": {
            "payload_size": DEFAULT_PAYLOAD_SIZE,
            "routing_size": DEFAULT_ROUTING_SIZE,
            "max_hops": 5,
        },
        "client": {"host": "127.0.0.1", "port": ports[-1]},
        "nodes": nodes,
    }
    config_path = tmp_path / "cluster.json"
    config_path.write_text(json.dumps(harness, sort_keys=True, indent=2), encoding="utf-8")
    return config_path, harness, node_ids
