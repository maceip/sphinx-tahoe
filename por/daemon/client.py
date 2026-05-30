"""P-OR client daemon entry point."""

from __future__ import annotations

import argparse
from typing import Sequence

from por.client import run_client_once
from por.config import ClusterConfig
from por.directory import load_public_snapshot_directory


def run_send(
    *,
    config_path: str,
    directory_snapshot: str,
    prompt: str,
    expertise: str | None = None,
    relay_path: Sequence[str] = (),
    timeout: float = 8.0,
) -> int:
    result = run_client_once(
        cluster=ClusterConfig.load(config_path),
        discovery_provider=load_public_snapshot_directory(directory_snapshot),
        prompt=prompt,
        requested_expertise=expertise,
        relay_path=tuple(relay_path),
        timeout=timeout,
    )
    print("client event=response_begin")
    print(result.response_text)
    print("client event=response_end")
    print("client event=client_logs_begin")
    print(result.client_logs)
    print("client event=client_logs_end")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    from por.daemon.main import legacy_client_main

    return legacy_client_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
