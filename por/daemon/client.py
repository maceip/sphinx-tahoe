"""P-OR client daemon entry point."""

from __future__ import annotations

import argparse
from typing import Sequence

from por.client import run_client_once
from por.config import ClusterConfig
from por.directory import load_public_snapshot_directory


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one P-OR client request.")
    parser.add_argument("--config", required=True, help="Cluster JSON config path")
    parser.add_argument("--directory-snapshot", required=True, help="Public directory snapshot JSON")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--expertise")
    parser.add_argument("--relay", action="append", default=[], help="Relay node id. Repeat in path order.")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args(argv)

    result = run_client_once(
        cluster=ClusterConfig.load(args.config),
        discovery_provider=load_public_snapshot_directory(args.directory_snapshot),
        prompt=args.prompt,
        requested_expertise=args.expertise,
        relay_path=tuple(args.relay),
        timeout=args.timeout,
    )
    print("client event=response_begin")
    print(result.response_text)
    print("client event=response_end")
    print("client event=client_logs_begin")
    print(result.client_logs)
    print("client event=client_logs_end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
