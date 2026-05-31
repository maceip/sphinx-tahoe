"""P-OR expert exit daemon."""

from __future__ import annotations

from typing import Sequence

from por.config import ClusterConfig, DaemonConfig, PorConfig
from por.log_events import PorLogEvent, emit_log_event
from por.node_runtime import WireNodeRuntime


def run_expert(*, config_path: str, node_id: str) -> int:
    cluster = ClusterConfig.load(config_path)
    runtime = WireNodeRuntime(cluster, node_id, role="expert")
    return runtime.serve_forever()


def run_expert_cluster(daemon: DaemonConfig, por_config: PorConfig) -> int:
    _emit_node_log(
        daemon, "daemon_start",
        fields={"supernode_enabled": daemon.supernode.enabled},
    )
    cluster = por_config.to_cluster_config()
    runtime = WireNodeRuntime(
        cluster,
        daemon.node_id,
        role="expert",
        logging=daemon.logging,
        provider=daemon.provider,
        expert_session=daemon.expert_session,
    )
    tls = daemon.transport
    if tls.certfile and tls.keyfile:
        from por.quic_runtime import serve_quic_forever
        return serve_quic_forever(runtime, certfile=tls.certfile, keyfile=tls.keyfile)
    if tls.dev_allow_insecure_tls:
        from por.quic_runtime import serve_quic_forever
        return serve_quic_forever(runtime, dev_localhost=True)
    return runtime.serve_forever()


def _emit_node_log(
    daemon: DaemonConfig,
    event: str,
    *,
    fields: dict[str, object] | None = None,
) -> None:
    emit_log_event(
        PorLogEvent(
            event=event,
            component="por-expert",
            node_id=daemon.node_id,
            role="expert",
            fields=fields or {},
        ),
        fmt=daemon.logging.fmt,
        redact_fields=frozenset(daemon.logging.redact_fields),
    )


def main(argv: Sequence[str] | None = None) -> int:
    from por.daemon.main import legacy_expert_main

    return legacy_expert_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
