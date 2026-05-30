"""P-OR client orchestrator and send path."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Sequence

from sphinxmix.OutfoxClient import packet_create
from sphinxmix.OutfoxNode import circuit_packet_decrypt
from sphinxmix.OutfoxParams import OutfoxParams

from .config import ClusterConfig
from .directory import DiscoveryProvider
from .envelope import PromptRequestEnvelope
from .expert_mode import ExpertModeConfig, prepare_expert_mode_request
from .expert_route import RouteIntent
from .node_runtime import (
    _b64d,
    _b64e,
    _send_frame,
    build_native_forward_plan,
    build_por1_forward_plan,
)
from .provider import stream_frontier_reply


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
    circuit_wire: str = "native",
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

    forward_path = tuple(relay_path) + (selected_peer_id,)
    _validate_forward_path(cluster, forward_path)
    response, stream_logs = send_prepared_envelope(
        cluster=cluster,
        forward_path=forward_path,
        envelope=prepared.envelope,
        timeout=timeout,
        circuit_wire=circuit_wire,
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
    circuit_wire: str = "native",
) -> tuple[str, list[str]]:
    """Send an already-prepared Layer 7 envelope over the current UDP wire API.

    circuit_wire:
      ``native`` — Outfox header circuit setup (default)
      ``por1`` — legacy POR1 blobs in routing_info (bridge compat)
    """

    if not forward_path:
        raise ValueError("forward_path is required")
    if circuit_wire not in {"native", "por1"}:
        raise ValueError(f"unsupported circuit_wire: {circuit_wire}")
    _validate_forward_path(cluster, forward_path)

    params = OutfoxParams(**cluster.params.outfox_kwargs())
    harness = cluster.to_harness_dict()
    client_addr = (cluster.client.host, cluster.client.port)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_sock.bind(client_addr)
    client_sock.settimeout(0.5)

    circuit_setup = None
    if circuit_wire == "por1":
        route_infos, client_peel_keys = build_por1_forward_plan(
            tuple(forward_path),
            selected_peer_id=envelope.selected_peer_id or forward_path[-1],
            routing_size=params.routing_size,
        )
    else:
        route_infos, circuit_setup, client_peel_keys = build_native_forward_plan(
            tuple(forward_path)
        )
    kem_keys = [bytes.fromhex(cluster.node(node_id).kem_pk_hex) for node_id in forward_path]
    header, payload = packet_create(
        params,
        route_infos,
        kem_keys,
        envelope.to_json().encode("utf-8"),
        circuit_setup=circuit_setup,
    )

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _send_frame(
            send_sock,
            harness,
            forward_path[0],
            {
                "kind": "forward",
                "header": _b64e(header),
                "payload": _b64e(payload),
            },
        )

        chunks: list[str] = []
        logs = [
            "client event=send_prepared_envelope selected={selected} forward_path={path} "
            "circuit_wire={wire}".format(
                selected=envelope.selected_peer_id or "none",
                path="/".join(forward_path),
                wire=circuit_wire,
            )
        ]
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _addr = client_sock.recvfrom(65535)
            except socket.timeout:
                continue
            frame = json.loads(data.decode("utf-8"))
            if frame.get("kind") != "circuit":
                continue
            plain = circuit_packet_decrypt(params, client_peel_keys, _b64d(frame["packet"]))
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
