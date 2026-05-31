import subprocess
import sys
import time
from pathlib import Path

import pytest

from por.client import run_client_once
from por.config import (
    ClusterConfig,
    PeerAddressConfig,
    TrustedReachabilityRelayConfig,
)
from por.directory import PublicManifestDirectory
from por.peer_address import PeerAddressRelay, UdpEndpoint
from por.provider import ProviderError
from tests.helpers import (
    collect_process_logs,
    demo_directory,
    shutdown_process_nodes,
    start_process_nodes,
    write_process_wire_cluster,
)
from tests.helpers import has_log_event, parse_json_log_events


def test_client_fallback_does_not_touch_wire(tmp_path):
    config_path, _harness, _node_ids = _write_cluster(tmp_path, node_count=3)
    cluster = ClusterConfig.load(config_path)

    with pytest.raises(ProviderError, match="POR_PROVIDER or daemon.provider is required"):
        run_client_once(
            cluster=cluster,
            discovery_provider=PublicManifestDirectory(records=tuple()),
            prompt="Explain basalt petrology.",
            requested_expertise="basalt petrology",
            relay_path=("relay1", "relay2"),
            timeout=0.5,
        )


def test_client_uses_peer_address_record_to_plan_relay_path(monkeypatch, tmp_path):
    config_path, _harness, _node_ids = _write_cluster(tmp_path, node_count=4)
    cluster = ClusterConfig.load(config_path)
    directory = demo_directory(tmp_path)
    secret = b"client-peer-address-secret"
    address_relay = PeerAddressRelay(
        relay_id="relay1",
        relay_endpoint=UdpEndpoint("127.0.0.1", 7001),
        secret=secret,
    )
    now = time.time()
    challenge = address_relay.request_registration(
        peer_id="expert_art",
        observed_endpoint=UdpEndpoint("127.0.0.1", 7003),
        now=now,
    )
    record = address_relay.confirm_registration(challenge, now=now + 1).to_public_dict()
    seen = {}

    def recording_send_prepared_envelope(**kwargs):
        seen["forward_path"] = kwargs["forward_path"]
        seen["dial_target"] = kwargs["dial_target"]
        return "[test expert response]", ["client event=test_stream"]

    monkeypatch.setattr("por.client.send_prepared_envelope", recording_send_prepared_envelope)

    result = run_client_once(
        cluster=cluster,
        discovery_provider=directory,
        prompt="What did Monet change about modern painting?",
        requested_expertise="Impressionist art history",
        relay_path=("relay2",),
        peer_address_config=PeerAddressConfig(
            enabled=True,
            records={"expert_art": record},
        ),
        trusted_reachability_relays=(
            TrustedReachabilityRelayConfig(
                relay_id="relay1",
                host=cluster.node("relay1").host,
                port=cluster.node("relay1").port,
                verify_key=secret.hex(),
            ),
        ),
        random_seed=3,
    )

    assert result.fallback_used is False
    assert seen["forward_path"] == ("relay1", "expert_art")
    assert seen["dial_target"].relay_id == "relay1"
    assert seen["dial_target"].host == cluster.node("relay1").host
    assert seen["dial_target"].port == cluster.node("relay1").port
    assert "event=peer_address_plan" in result.client_logs
    assert "event=dial_target" in result.client_logs
    assert "event=peer_address_ignored_static_relay_path" in result.client_logs
    assert "event=peer_address_relay_path" in result.client_logs


def test_client_rejects_untrusted_peer_address_relay_before_send(monkeypatch, tmp_path):
    config_path, _harness, _node_ids = _write_cluster(tmp_path, node_count=4)
    cluster = ClusterConfig.load(config_path)
    directory = demo_directory(tmp_path)
    address_relay = PeerAddressRelay(
        relay_id="untrusted-relay",
        relay_endpoint=UdpEndpoint("203.0.113.55", 4433),
        secret=b"untrusted-peer-address-secret",
    )
    challenge = address_relay.request_registration(
        peer_id="expert_art",
        observed_endpoint=UdpEndpoint("127.0.0.1", 7003),
        now=time.time(),
    )
    record = address_relay.confirm_registration(challenge).to_public_dict()

    def forbidden_send_prepared_envelope(**_kwargs):
        raise AssertionError("untrusted peer-address record must not touch socket send")

    monkeypatch.setattr("por.client.send_prepared_envelope", forbidden_send_prepared_envelope)

    with pytest.raises(ProviderError, match="POR_PROVIDER or daemon.provider is required"):
        run_client_once(
            cluster=cluster,
            discovery_provider=directory,
            prompt="What did Monet change about modern painting?",
            requested_expertise="Impressionist art history",
            peer_address_config=PeerAddressConfig(enabled=True, records={"expert_art": record}),
            trusted_reachability_relays=(),
            random_seed=3,
        )


def test_client_rejects_tampered_peer_address_signature_before_send(monkeypatch, tmp_path):
    config_path, _harness, _node_ids = _write_cluster(tmp_path, node_count=4)
    cluster = ClusterConfig.load(config_path)
    directory = demo_directory(tmp_path)
    secret = b"client-peer-address-secret"
    address_relay = PeerAddressRelay(
        relay_id="relay1",
        relay_endpoint=UdpEndpoint("127.0.0.1", 7001),
        secret=secret,
    )
    challenge = address_relay.request_registration(
        peer_id="expert_art",
        observed_endpoint=UdpEndpoint("127.0.0.1", 7003),
        now=time.time(),
    )
    record = address_relay.confirm_registration(challenge).to_public_dict()
    record["relay_candidates"][0]["endpoint"]["port"] = 65530

    def forbidden_send_prepared_envelope(**_kwargs):
        raise AssertionError("bad peer-address signature must not touch socket send")

    monkeypatch.setattr("por.client.send_prepared_envelope", forbidden_send_prepared_envelope)

    with pytest.raises(ProviderError, match="POR_PROVIDER or daemon.provider is required"):
        run_client_once(
            cluster=cluster,
            discovery_provider=directory,
            prompt="What did Monet change about modern painting?",
            requested_expertise="Impressionist art history",
            peer_address_config=PeerAddressConfig(enabled=True, records={"expert_art": record}),
            trusted_reachability_relays=(
                TrustedReachabilityRelayConfig(
                    relay_id="relay1",
                    host=cluster.node("relay1").host,
                    port=cluster.node("relay1").port,
                    verify_key=secret.hex(),
                ),
            ),
            random_seed=3,
        )


@pytest.mark.integration
@pytest.mark.product
def test_por_client_daemon_streams_over_process_nodes(tmp_path):
    config_path, harness, node_ids = _write_cluster(tmp_path, node_count=4)
    directory_path = tmp_path / "directory-snapshot.json"
    demo_directory(tmp_path).save_snapshot(directory_path)

    procs = start_process_nodes(config_path, node_ids)
    try:
        time.sleep(0.35)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "por",
                "send",
                "--config",
                str(config_path),
                "--directory-snapshot",
                str(directory_path),
                "--prompt",
                "What did Monet change about modern painting?",
                "--expertise",
                "Impressionist art history",
                "--relay",
                "relay1",
                "--relay",
                "relay2",
                "--timeout",
                "8",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=12,
        )
    finally:
        shutdown_process_nodes(harness, node_ids)
        node_logs = collect_process_logs(procs)

    assert proc.returncode == 0, proc.stdout + "\n" + node_logs
    assert "[provider_error]" in proc.stdout
    assert "POR_PROVIDER or daemon.provider is required" in proc.stdout
    assert "client event=response_begin" in proc.stdout
    assert "client event=stream_chunk" in proc.stdout
    events = parse_json_log_events(node_logs)
    assert has_log_event(events, "forward_hop")
    assert has_log_event(events, "expert_exit")
    assert has_log_event(events, "forward_hop", field="prompt_visible", value=False)
    assert has_log_event(events, "expert_exit", field="prompt_visible", value=True)


def _write_cluster(tmp_path: Path, *, node_count: int):
    return write_process_wire_cluster(tmp_path, node_count=node_count)
