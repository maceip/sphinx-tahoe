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
    upnp_mapping = _try_upnp_on_startup(daemon)
    _emit_node_log(
        daemon, "daemon_start",
        fields={
            "supernode_enabled": daemon.supernode.enabled,
            "upnp": upnp_mapping.method if upnp_mapping else "none",
            "upnp_port": upnp_mapping.external_port if upnp_mapping else None,
        },
    )
    cluster = por_config.to_cluster_config()
    runtime = WireNodeRuntime(
        cluster,
        daemon.node_id,
        role="expert",
        logging=daemon.logging,
        provider=daemon.provider,
    )
    runtime.upnp_mapping = upnp_mapping
    tls = daemon.transport
    if tls.certfile and tls.keyfile:
        from por.quic_runtime import serve_quic_forever
        return serve_quic_forever(runtime, certfile=tls.certfile, keyfile=tls.keyfile)
    if tls.dev_allow_insecure_tls:
        from por.quic_runtime import serve_quic_forever
        return serve_quic_forever(runtime, dev_localhost=True)
    return runtime.serve_forever()


def _try_upnp_on_startup(daemon: DaemonConfig):
    """Try UPnP/NAT-PMP port mapping on expert startup. Returns mapping or None."""
    try:
        from por.upnp import try_port_mapping
        bind_port = daemon.transport.bind.port if daemon.transport.bind else 4433
        result = try_port_mapping(bind_port, lease_seconds=7200, description="P-OR Expert")
        if result.success:
            _emit_node_log(daemon, "upnp_mapped", fields={
                "method": result.mapping.method,
                "external_port": result.mapping.external_port,
                "external_ip": result.mapping.external_ip,
                "lease_seconds": result.mapping.lease_seconds,
            })
            return result.mapping
        _emit_node_log(daemon, "upnp_failed", level="info",
                       fields={"error": result.error})
    except Exception as e:
        _emit_node_log(daemon, "upnp_error", level="warning",
                       fields={"error": str(e)})
    return None


def _emit_node_log(
    daemon: DaemonConfig,
    event: str,
    *,
    level: str = "info",
    fields: dict[str, object] | None = None,
) -> None:
    emit_log_event(
        PorLogEvent(
            event=event,
            component="por-expert",
            node_id=daemon.node_id,
            role="expert",
            level=level,
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
