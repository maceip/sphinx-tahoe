"""P-OR relay daemon."""

from __future__ import annotations

from typing import Sequence

from por.config import ClusterConfig, DaemonConfig
from por.node_runtime import WireNodeRuntime


def run_relay(*, config_path: str, node_id: str) -> int:
    cluster = ClusterConfig.load(config_path)
    runtime = WireNodeRuntime(cluster, node_id, role="relay")
    return runtime.serve_forever()


def run_relay_cluster(daemon: DaemonConfig) -> int:
    raise SystemExit(
        "por run: relay from por.config.v1 alone is not wired yet (no kem keys in "
        "daemon schema). Use cluster harness: `por relay --config cluster.json "
        f"--node-id {daemon.node_id}` — tracked in production_arc convergence checklist."
    )


def main(argv: Sequence[str] | None = None) -> int:
    from por.daemon.main import legacy_relay_main

    return legacy_relay_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
