import json
import tempfile
from pathlib import Path

from por.config import ClusterConfig
from por.node_runtime import WireNodeRuntime


def test_relay_runtime_rejects_exit_role():
    harness = {
        "params": {"payload_size": 2048, "routing_size": 96, "max_hops": 5},
        "client": {"host": "127.0.0.1", "port": 1},
        "nodes": {
            "relay1": {
                "host": "127.0.0.1",
                "port": 2,
                "kem_pk": "00" * 32,
                "kem_sk": "11" * 32,
                "role": "relay",
            }
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cfg.json"
        path.write_text(json.dumps(harness), encoding="utf-8")
        cluster = ClusterConfig.load(path)
        runtime = WireNodeRuntime(cluster, "relay1", role="relay")
        assert runtime.role == "relay"


def test_expert_runtime_role():
    harness = {
        "params": {"payload_size": 2048, "routing_size": 96, "max_hops": 5},
        "client": {"host": "127.0.0.1", "port": 1},
        "nodes": {
            "expert_art": {
                "host": "127.0.0.1",
                "port": 3,
                "kem_pk": "00" * 32,
                "kem_sk": "11" * 32,
                "role": "expert",
            }
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cfg.json"
        path.write_text(json.dumps(harness), encoding="utf-8")
        cluster = ClusterConfig.load(path)
        runtime = WireNodeRuntime(cluster, "expert_art", role="expert")
        assert runtime.role == "expert"
