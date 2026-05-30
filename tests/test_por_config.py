import json

import pytest

from por.config import (
    CONFIG_VERSION,
    ROLE_CLIENT,
    ROLE_EXPERT,
    ROLE_RELAY,
    TRANSPORT_QUIC_H3,
    DaemonConfig,
    EndpointConfig,
    ClusterConfig,
    PorConfig,
    TransportConfig,
    load_config,
)


def test_single_daemon_config_loads_with_secure_transport_default(tmp_path):
    path = tmp_path / "client.json"
    path.write_text(
        json.dumps(
            {
                "node_id": "client-a",
                "role": ROLE_CLIENT,
                "transport": {"kind": TRANSPORT_QUIC_H3, "host": "127.0.0.1", "port": 4443},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)
    daemon = config.daemon()

    assert daemon.node_id == "client-a"
    assert daemon.transport.verify_tls is True
    assert daemon.transport.bind == EndpointConfig("127.0.0.1", 4443)


def test_multi_daemon_config_round_trips_and_exports_expert_mode_config():
    config = PorConfig.from_dict(
        {
            "version": CONFIG_VERSION,
            "default_node_id": "relay-a",
            "daemons": {
                "relay-a": {
                    "role": ROLE_RELAY,
                    "transport": {"port": 5001},
                    "peers": {"expert-a": {"host": "127.0.0.1", "port": 5002}},
                },
                "expert-a": {
                    "role": ROLE_EXPERT,
                    "transport": {"port": 5002},
                    "provider": {"provider": "anthropic", "model": "claude", "api_key_env": "ANTHROPIC_API_KEY"},
                    "expert_routing": {"min_pool_size": 5, "fallback_provider": "frontier"},
                },
            },
        }
    )

    relay = config.daemon()
    expert = config.daemon("expert-a")

    assert relay.peers["expert-a"].endpoint.port == 5002
    assert expert.provider is not None
    assert expert.provider.resolve_api_key({"ANTHROPIC_API_KEY": "secret"}) == "secret"
    assert expert.expert_routing.to_expert_mode_config().min_pool_size == 5
    assert config.to_dict()["daemons"]["expert-a"]["role"] == ROLE_EXPERT


def test_insecure_tls_requires_dev_opt_in():
    with pytest.raises(ValueError, match="dev_allow_insecure_tls"):
        TransportConfig(verify_tls=False)

    config = TransportConfig(verify_tls=False, dev_allow_insecure_tls=True)

    assert config.verify_tls is False


def test_daemon_config_rejects_bad_role():
    with pytest.raises(ValueError, match="unsupported daemon role"):
        DaemonConfig(node_id="node-a", role="bad-role")


def test_cluster_config_loads_current_demo_shape(tmp_path):
    path = tmp_path / "cluster.json"
    path.write_text(
        json.dumps(
            {
                "params": {"payload_size": 2048, "routing_size": 96, "max_hops": 5},
                "client": {"host": "127.0.0.1", "port": 7000},
                "nodes": {
                    "relay1": {
                        "host": "127.0.0.1",
                        "port": 7001,
                        "kem_pk": "00" * 32,
                        "kem_sk": "11" * 32,
                        "role": "relay",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    cluster = ClusterConfig.load(path)

    assert cluster.params.routing_size == 96
    assert cluster.node("relay1").kem_pk_hex == "00" * 32
    assert cluster.to_harness_dict()["nodes"]["relay1"]["kem_sk"] == "11" * 32
