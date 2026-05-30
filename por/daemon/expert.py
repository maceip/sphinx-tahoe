"""P-OR expert exit daemon."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from por.config import ClusterConfig
from por.node_runtime import WireNodeRuntime


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a P-OR expert exit node.")
    parser.add_argument("--config", required=True, help="Cluster JSON config path")
    parser.add_argument("--node-id", required=True, help="Expert node id from config.nodes")
    args = parser.parse_args(argv)

    cluster = ClusterConfig.load(args.config)
    runtime = WireNodeRuntime(cluster, args.node_id, role="expert")
    return runtime.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
