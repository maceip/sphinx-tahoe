"""P-OR client orchestrator and send path.

Layer 7 contract: all app payloads must come from ``prepare_expert_mode_request()``.
This module must not construct ``PromptRequestEnvelope`` directly.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Mapping, Sequence

from sphinxmix.OutfoxClient import packet_create
from sphinxmix.OutfoxNode import circuit_packet_decrypt
from sphinxmix.OutfoxParams import OutfoxParams

from .config import ClusterConfig, PeerAddressConfig
from .directory import DiscoveryProvider
from .envelope import PromptRequestEnvelope
from .expert_mode import ExpertModeConfig, prepare_expert_mode_request
from .expert_route import RouteIntent
from .node_runtime import build_native_forward_plan
from .peer_address import ROUTE_RELAY, build_dial_plan, peer_address_record_from_dict
from .provider import stream_frontier_reply
from .wire_frame import encode_forward, encode_shutdown, decode_datagram


@dataclass(frozen=True)
class ClientRunResult:
    selected_peer_id: str | None
    degraded_anonymity: bool
    fallback_used: bool
    response_text: str
    client_logs: str


def run_client_once(
    *,
    cluster: ClusterConfig,
    discovery_provider: DiscoveryProvider,
    prompt: str,
    requested_expertise: str | None = None,
    relay_path: Sequence[str] = (),
    timeout: float = 8.0,
    expert_mode_config: ExpertModeConfig | None = None,
    random_seed: int | None = None,
    peer_address_config: PeerAddressConfig | None = None,
    peer_address_records: Mapping[str, dict[str, object]] | None = None,
) -> ClientRunResult:
    """Plan one Expert Mode request and send the prepared envelope if selected."""

    intent = RouteIntent(
        prompt=prompt,
        requested_expertise=requested_expertise,
        random_seed=random_seed,
    )
    prepared = prepare_expert_mode_request(
        intent,
        discovery_provider,
        expert_mode_config or ExpertModeConfig(),
    )

    logs = [
        "client event=expert_plan selected={selected} degraded_anonymity={degraded} "
        "fallback_used={fallback} pool_tier={pool_tier}".format(
            selected=prepared.trace.selected_peer_id or "none",
            degraded=str(prepared.plan.pool.degraded_anonymity).lower(),
            fallback=str(not prepared.use_expert).lower(),
            pool_tier=prepared.trace.pool_tier,
        )
    ]

    if not prepared.use_expert or prepared.envelope is None:
        response = "".join(stream_frontier_reply(prompt, prepared.trace.fallback_reason))
        return ClientRunResult(
            selected_peer_id=None,
            degraded_anonymity=prepared.plan.pool.degraded_anonymity,
            fallback_used=True,
            response_text=response,
            client_logs="\n".join(logs),
        )

    selected_peer_id = prepared.envelope.selected_peer_id
    if selected_peer_id not in cluster.nodes:
        response = "".join(stream_frontier_reply(prompt, "selected expert peer not in cluster"))
        logs.append("client event=selected_peer_missing fallback_used=true")
        return ClientRunResult(
            selected_peer_id=selected_peer_id,
            degraded_anonymity=prepared.plan.pool.degraded_anonymity,
            fallback_used=True,
            response_text=response,
            client_logs="\n".join(logs),
        )

    relay_path, dial_logs = _plan_relay_path_from_peer_address(
        selected_peer_id=selected_peer_id,
        relay_path=tuple(relay_path),
        peer_address_config=peer_address_config,
        peer_address_records=peer_address_records,
    )
    logs.extend(dial_logs)
    forward_path = tuple(relay_path) + (selected_peer_id,)
    _validate_forward_path(cluster, forward_path)
    response, stream_logs = send_prepared_envelope(
        cluster=cluster,
        forward_path=forward_path,
        envelope=prepared.envelope,
        timeout=timeout,
    )
    logs.extend(stream_logs)
    return ClientRunResult(
        selected_peer_id=selected_peer_id,
        degraded_anonymity=prepared.plan.pool.degraded_anonymity,
        fallback_used=False,
        response_text=response,
        client_logs="\n".join(logs),
    )


def send_prepared_envelope(
    *,
    cluster: ClusterConfig,
    forward_path: Sequence[str],
    envelope: PromptRequestEnvelope,
    timeout: float = 8.0,
) -> tuple[str, list[str]]:
    """Send a prepared Layer 7 envelope via canonical binary UDP datagrams."""

    if not forward_path:
        raise ValueError("forward_path is required")
    _validate_forward_path(cluster, forward_path)

    params = OutfoxParams(**cluster.params.outfox_kwargs())
    client_addr = (cluster.client.host, cluster.client.port)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_sock.bind(client_addr)
    client_sock.settimeout(0.5)

    route_infos, circuit_setup, client_peel_keys = build_native_forward_plan(
        tuple(forward_path))
    kem_keys = [bytes.fromhex(cluster.node(nid).kem_pk_hex) for nid in forward_path]
    header, payload = packet_create(
        params, route_infos, kem_keys,
        envelope.to_json().encode("utf-8"),
        circuit_setup=circuit_setup,
    )

    first_node = cluster.node(forward_path[0])
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        send_sock.sendto(encode_forward(header, payload), (first_node.host, first_node.port))

        chunks: list[str] = []
        logs = [
            f"client event=send_prepared_envelope selected={envelope.selected_peer_id or 'none'} "
            f"forward_path={'/'.join(forward_path)} wire=binary"
        ]
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _addr = client_sock.recvfrom(65535)
            except socket.timeout:
                continue
            kind, body, _ = decode_datagram(data, params.payload_size)
            if kind != "circuit":
                continue
            plain = circuit_packet_decrypt(params, client_peel_keys, body)
            if plain is None:
                logs.append("client event=stream_corrupt")
                continue
            chunk = json.loads(plain.decode("utf-8"))
            logs.append(f"client event=stream_chunk seq={chunk['seq']} bytes={len(chunk['data'])}")
            if chunk.get("done"):
                break
            chunks.append(chunk["data"])
        else:
            raise TimeoutError("timed out waiting for streamed return path")
        return "".join(chunks), logs
    finally:
        client_sock.close()
        send_sock.close()


def _validate_forward_path(cluster: ClusterConfig, forward_path: Sequence[str]) -> None:
    missing = [node_id for node_id in forward_path if node_id not in cluster.nodes]
    if missing:
        raise ValueError(f"forward_path contains unknown nodes: {', '.join(missing)}")


def _plan_relay_path_from_peer_address(
    *,
    selected_peer_id: str | None,
    relay_path: tuple[str, ...],
    peer_address_config: PeerAddressConfig | None,
    peer_address_records: Mapping[str, dict[str, object]] | None,
) -> tuple[tuple[str, ...], list[str]]:
    """Use peer-address records for route planning without changing transport IO."""

    logs: list[str] = []
    if (
        selected_peer_id is None
        or peer_address_config is None
        or not peer_address_config.enabled
    ):
        return relay_path, logs

    records = peer_address_records or peer_address_config.records
    raw_record = records.get(selected_peer_id)
    if raw_record is None:
        logs.append(f"client event=peer_address_missing peer_id={selected_peer_id}")
        return relay_path, logs

    record = peer_address_record_from_dict(dict(raw_record))
    plan = build_dial_plan(
        record,
        allow_direct=peer_address_config.allow_direct,
        prefer_direct=peer_address_config.prefer_direct,
    )
    primary_kind = plan.primary.kind if plan.primary else "none"
    logs.append(
        "client event=peer_address_plan peer_id={peer_id} contactable={contactable} "
        "primary={primary} fallback_count={fallback_count}".format(
            peer_id=selected_peer_id,
            contactable=str(plan.contactable).lower(),
            primary=primary_kind,
            fallback_count=len(plan.fallbacks),
        )
    )
    for warning in plan.warnings:
        logs.append(
            f"client event=peer_address_warning peer_id={selected_peer_id} warning={warning!r}"
        )

    relay_routes = [
        route
        for route in ((plan.primary,) if plan.primary else ()) + plan.fallbacks
        if route.kind == ROUTE_RELAY and route.relay_id
    ]
    if relay_path or not relay_routes:
        return relay_path, logs

    planned = (relay_routes[0].relay_id,)
    logs.append(
        "client event=peer_address_relay_path peer_id={peer_id} relay_path={path}".format(
            peer_id=selected_peer_id,
            path="/".join(planned),
        )
    )
    return planned, logs
