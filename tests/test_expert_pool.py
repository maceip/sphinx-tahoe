import json

from por.expert_pool import (
    ExpertAdvertisement,
    ExpertMatcherIndex,
    PoolBackedDiscoveryProvider,
    select_pool_index,
    simulate_expert_pool_routing,
)
from por.client import run_client_once
from por.daemon.client import run_pool_send
from por.expert_mode import ExpertModeConfig
from por.node_runtime import WireNodeRuntime
from tests.harness import mixnet_harness


def test_pool_commitment_selects_verifiable_member():
    matcher = ExpertMatcherIndex(matcher_id="matcher-a", signer_key="matcher-secret")
    now = 1000.0
    for idx in range(12):
        matcher.ingest(
            ExpertAdvertisement.v0(
                expert_peer_id=f"expert-{idx}",
                manifest_digest=f"manifest-{idx}",
                topic_keys=("topic-x",),
                capability_keys=("expert_session",),
                reachability_ref=f"relay://expert-{idx}",
                quality_score=0.5 + idx / 30,
                availability_score=0.9,
                issued_at=now,
                expires_at=now + 60,
                sequence=idx,
                signer_key=f"expert-secret-{idx}",
            ),
            now=now,
        )

    commitment, members, proof = matcher.build_pool(
        topic_key="topic-x",
        request_id="request-1",
        client_nonce="client-nonce",
        min_pool_size=8,
        max_pool_size=10,
        now=now,
    )

    assert commitment.candidate_count == 10
    assert commitment.verify_signature("matcher-secret")
    assert len(members) == 10
    assert proof.verify(commitment)
    assert proof.selected_index == select_pool_index(
        commitment,
        request_id="request-1",
        client_nonce="client-nonce",
    )
    assert proof.selected_member in members


def test_ad_and_pool_signatures_detect_tampering():
    ad = ExpertAdvertisement.v0(
        expert_peer_id="expert-a",
        manifest_digest="manifest-a",
        topic_keys=("topic-x",),
        capability_keys=("expert_session",),
        reachability_ref="relay://expert-a",
        quality_score=0.9,
        availability_score=0.9,
        issued_at=1000.0,
        expires_at=1100.0,
        sequence=1,
        signer_key="expert-secret",
    )
    assert ad.verify_signature("expert-secret")
    tampered_ad = ad.__class__(**{**ad.to_dict(), "quality_score": 0.1})
    assert not tampered_ad.verify_signature("expert-secret")

    matcher = ExpertMatcherIndex(matcher_id="matcher-a", signer_key="matcher-secret")
    for idx in range(8):
        matcher.ingest(
            ExpertAdvertisement.v0(
                expert_peer_id=f"expert-{idx}",
                manifest_digest=f"manifest-{idx}",
                topic_keys=("topic-x",),
                capability_keys=("expert_session",),
                reachability_ref=f"relay://expert-{idx}",
                quality_score=0.8,
                availability_score=0.9,
                issued_at=1000.0,
                expires_at=1100.0,
                sequence=idx,
                signer_key=f"expert-secret-{idx}",
            ),
            now=1000.0,
        )
    commitment, _members, _proof = matcher.build_pool(
        topic_key="topic-x",
        request_id="request-1",
        client_nonce="nonce",
        min_pool_size=8,
        now=1000.0,
    )
    assert commitment.verify_signature("matcher-secret")
    tampered_commitment = commitment.__class__(
        **{**commitment.to_dict(), "candidate_count": commitment.candidate_count + 1}
    )
    assert not tampered_commitment.verify_signature("matcher-secret")


def test_expired_ads_do_not_enter_pools():
    matcher = ExpertMatcherIndex(matcher_id="matcher-a", signer_key="matcher-secret")
    matcher.ingest(
        ExpertAdvertisement.v0(
            expert_peer_id="expired",
            manifest_digest="manifest",
            topic_keys=("topic-x",),
            capability_keys=("expert_session",),
            reachability_ref="relay://expired",
            quality_score=1.0,
            availability_score=1.0,
            issued_at=1000.0,
            expires_at=1001.0,
            sequence=1,
            signer_key="expert-secret",
        ),
        now=1002.0,
    )

    try:
        matcher.build_pool(
            topic_key="topic-x",
            request_id="request-1",
            client_nonce="client-nonce",
            min_pool_size=1,
            now=1002.0,
        )
    except ValueError as exc:
        assert "not enough experts" in str(exc)
    else:
        raise AssertionError("expired ad should not produce a pool")


def test_1000_client_simulation_has_bounded_fast_pools():
    result = simulate_expert_pool_routing(clients=1000, experts=500, topics=32, seed=9)

    assert result.client_count == 1000
    assert result.success_count == 1000
    assert result.por_client_success_count == 1000
    assert result.failure_count == 0
    assert result.average_pool_size == 20
    assert result.p95_lookup_ms < 15
    assert result.max_expert_share < 0.04


def test_pool_backed_provider_runs_through_real_por_wire_client():
    now = 1000.0
    matcher = ExpertMatcherIndex(matcher_id="matcher-a", signer_key="matcher-secret")
    matcher.ingest(
        ExpertAdvertisement.v0(
            expert_peer_id="expert_art",
            manifest_digest="manifest-art",
            topic_keys=("topic-x",),
            capability_keys=("expert_session",),
            reachability_ref="cluster://expert_art",
            quality_score=0.9,
            availability_score=0.9,
            issued_at=now,
            expires_at=now + 60,
            sequence=1,
            signer_key="expert-secret",
        ),
        now=now,
    )
    provider = PoolBackedDiscoveryProvider(
        matcher=matcher,
        min_pool_size=1,
        max_pool_size=1,
        now=now,
    )
    provider.next_request_context(
        request_id="request-wire",
        client_nonce="client-wire",
        now=now,
    )

    with mixnet_harness() as net:
        cluster, nodes, client_sock = net.wire_cluster(
            ("relay1", "relay"),
            ("expert_art", "expert"),
            payload_size=2048,
            routing_size=96,
        )
        net.serve(WireNodeRuntime(cluster, "relay1", role="relay"), nodes["relay1"].sock)
        net.serve(WireNodeRuntime(cluster, "expert_art", role="expert"), nodes["expert_art"].sock)

        result = run_client_once(
            cluster=cluster,
            discovery_provider=provider,
            prompt="Need expert for topic-x",
            requested_expertise="topic-x",
            relay_path=("relay1",),
            expert_mode_config=ExpertModeConfig(min_pool_size=1),
            timeout=6.0,
            client_sock=client_sock,
        )

    assert result.fallback_used is False
    assert result.selected_peer_id == "expert_art"
    assert "[wire-harness expert_reply]" in result.response_text
    assert provider.last_commitment is not None
    assert provider.last_proof is not None
    assert provider.last_proof.verify(provider.last_commitment)


def test_pool_send_runs_existing_client_wire_path(tmp_path):
    now = 1000.0
    with mixnet_harness() as net:
        cluster, nodes, client_sock = net.wire_cluster(
            ("relay1", "relay"),
            ("expert_art", "expert"),
            payload_size=2048,
            routing_size=96,
        )
        cluster_path = tmp_path / "cluster.json"
        cluster_path.write_text(json.dumps(cluster.to_harness_dict()), encoding="utf-8")
        ad = ExpertAdvertisement.v0(
            expert_peer_id="expert_art",
            manifest_digest="manifest-art",
            topic_keys=("topic-x",),
            capability_keys=("expert_session",),
            reachability_ref="cluster://expert_art",
            quality_score=0.95,
            availability_score=0.95,
            issued_at=now,
            expires_at=now + 60,
            sequence=1,
            signer_key="expert-secret",
        )
        ads_path = tmp_path / "ads.jsonl"
        ads_path.write_text(json.dumps(ad.to_dict(), sort_keys=True) + "\n", encoding="utf-8")

        net.serve(WireNodeRuntime(cluster, "relay1", role="relay"), nodes["relay1"].sock)
        net.serve(WireNodeRuntime(cluster, "expert_art", role="expert"), nodes["expert_art"].sock)

        result = run_pool_send(
            config_path=str(cluster_path),
            advertisements_path=str(ads_path),
            topic="topic-x",
            prompt="Need expert for topic-x",
            relay_path=("relay1",),
            min_pool_size=1,
            max_pool_size=1,
            request_id="request-wire",
            client_nonce="client-wire",
            now=now,
            timeout=6.0,
            client_sock=client_sock,
        )

    assert result.fallback_used is False
    assert result.selected_peer_id == "expert_art"
    assert "[wire-harness expert_reply]" in result.response_text
    assert "mode=pool_commitment_v0" in result.client_logs
    assert "pool_id=" in result.client_logs
