"""Unified P-OR binary entry point.

Everyone installs and runs ``por``. Subcommands select behavior; legacy
``por-relay`` / ``por-expert`` / ``por-client`` console scripts delegate here.

Target product shape:
  - default: client (send prompts)
  - supernode: same binary + config (public IP, relay registration)
  - optional local HTTP/SSE on the client process (future)
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from por.config import (
    ROLE_CLIENT,
    ROLE_DIRECTORY,
    ROLE_EXPERT,
    ROLE_RELAY,
    load_config,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="por",
        description="P-OR — one binary for client, relay, expert, and directory service.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    send = sub.add_parser("send", help="Run one client request (prepare + send envelope).")
    send.add_argument("--config", required=True, help="Cluster JSON config path")
    send.add_argument("--directory-snapshot", required=True, help="Public directory snapshot JSON")
    send.add_argument("--prompt", required=True)
    send.add_argument("--expertise")
    send.add_argument("--relay", action="append", default=[], help="Relay node id. Repeat in path order.")
    send.add_argument("--timeout", type=float, default=8.0)

    relay = sub.add_parser("relay", help="Run a relay node (supernode when promoted).")
    relay.add_argument("--config", required=True, help="Cluster JSON config path")
    relay.add_argument("--node-id", required=True, help="Node id from config.nodes")

    expert = sub.add_parser("expert", help="Run an expert exit node.")
    expert.add_argument("--config", required=True, help="Cluster JSON config path")
    expert.add_argument("--node-id", required=True, help="Expert node id from config.nodes")

    directory = sub.add_parser("directory", help="Serve a public directory snapshot over HTTP.")
    directory.add_argument("--snapshot", required=True, help="Directory snapshot JSON file")
    directory.add_argument("--host", default="127.0.0.1")
    directory.add_argument("--port", type=int, default=8765)
    directory.add_argument("--route", default="/snapshot")

    quality = sub.add_parser("quality", help="Record/review/aggregate expert quality events.")
    quality_sub = quality.add_subparsers(dest="quality_command", required=True)
    quality_record = quality_sub.add_parser("record", help="Record a request event.")
    quality_record.add_argument("--store", required=True)
    quality_record.add_argument("--event", required=True)
    for feedback_name in ("feedback", "review"):
        quality_feedback = quality_sub.add_parser(
            feedback_name,
            help="Submit feedback for a validated completed job." if feedback_name == "feedback" else "Alias for feedback.",
        )
        quality_feedback.add_argument("--store", required=True)
        quality_feedback.add_argument("--request-id", required=True)
        quality_feedback.add_argument("--rating", required=True)
        quality_feedback.add_argument("--complaint-reason")
        quality_feedback.add_argument("--judge-score", type=float)
        quality_feedback.add_argument("--probe-id")
        quality_feedback.add_argument("--timestamp")
        quality_feedback.add_argument("--signature")
    quality_aggregate = quality_sub.add_parser("aggregate", help="Aggregate manifest quality signals.")
    quality_aggregate.add_argument("--store", required=True)
    quality_aggregate.add_argument("--manifest-id", required=True)

    run = sub.add_parser(
        "run",
        help="Run from a por.config.v1 daemon JSON (role selects subcommand).",
    )
    run.add_argument("--config", required=True, help="por.config.v1 JSON path")
    run.add_argument("--node-id", help="Daemon node id when config lists multiple")

    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "send":
        from por.daemon.client import run_send

        return run_send(
            config_path=args.config,
            directory_snapshot=args.directory_snapshot,
            prompt=args.prompt,
            expertise=args.expertise,
            relay_path=tuple(args.relay),
            timeout=args.timeout,
        )

    if args.command == "relay":
        from por.daemon.relay import run_relay

        return run_relay(config_path=args.config, node_id=args.node_id)

    if args.command == "expert":
        from por.daemon.expert import run_expert

        return run_expert(config_path=args.config, node_id=args.node_id)

    if args.command == "directory":
        from por.daemon.directory import run_directory_server

        return run_directory_server(
            snapshot_path=args.snapshot,
            host=args.host,
            port=args.port,
            route=args.route,
        )

    if args.command == "quality":
        from por import quality

        argv = [args.quality_command, "--store", args.store]
        if args.quality_command == "record":
            argv.extend(["--event", args.event])
        elif args.quality_command in {"feedback", "review"}:
            argv.extend(["--request-id", args.request_id, "--rating", args.rating])
            for name in ("complaint_reason", "judge_score", "probe_id", "timestamp", "signature"):
                value = getattr(args, name)
                if value is not None:
                    argv.extend([f"--{name.replace('_', '-')}", str(value)])
        elif args.quality_command == "aggregate":
            argv.extend(["--manifest-id", args.manifest_id])
        return quality.main(argv)

    if args.command == "run":
        return _run_from_daemon_config(args.config, node_id=args.node_id)

    raise ValueError(f"unknown command: {args.command}")


def _run_from_daemon_config(config_path: str, *, node_id: str | None) -> int:
    por_cfg = load_config(config_path)
    daemon = por_cfg.daemon(node_id)

    if daemon.role == ROLE_RELAY:
        from por.daemon.relay import run_relay_cluster

        return run_relay_cluster(daemon, por_cfg)
    if daemon.role == ROLE_EXPERT:
        from por.daemon.expert import run_expert_cluster

        return run_expert_cluster(daemon, por_cfg)
    if daemon.role == ROLE_CLIENT:
        from por.daemon.client import run_client_from_daemon

        return run_client_from_daemon(daemon, por_cfg)
    if daemon.role == ROLE_DIRECTORY:
        from por.daemon.directory import run_directory_from_daemon

        return run_directory_from_daemon(daemon, por_cfg)

    raise SystemExit(f"por run: unsupported daemon role {daemon.role!r}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return dispatch(args)


def _legacy_notice(old_name: str, new_argv: Sequence[str]) -> None:
    print(
        f"{old_name} is deprecated; use `por {' '.join(new_argv)}` (same binary).",
        file=sys.stderr,
    )


def legacy_relay_main(argv: Sequence[str] | None = None) -> int:
    _legacy_notice("por-relay", ("relay",))
    parser = argparse.ArgumentParser(description="Run a P-OR relay node.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--node-id", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    from por.daemon.relay import run_relay

    return run_relay(config_path=args.config, node_id=args.node_id)


def legacy_expert_main(argv: Sequence[str] | None = None) -> int:
    _legacy_notice("por-expert", ("expert",))
    parser = argparse.ArgumentParser(description="Run a P-OR expert exit node.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--node-id", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    from por.daemon.expert import run_expert

    return run_expert(config_path=args.config, node_id=args.node_id)


def legacy_client_main(argv: Sequence[str] | None = None) -> int:
    _legacy_notice("por-client", ("send",))
    parser = argparse.ArgumentParser(description="Run one P-OR client request.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--directory-snapshot", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--expertise")
    parser.add_argument("--relay", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    from por.daemon.client import run_send

    return run_send(
        config_path=args.config,
        directory_snapshot=args.directory_snapshot,
        prompt=args.prompt,
        expertise=args.expertise,
        relay_path=tuple(args.relay),
        timeout=args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
