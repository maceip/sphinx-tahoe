from por.expert_pool import (
    ExpertAdvertisement,
    ExpertMatcherIndex,
    select_pool_index,
    simulate_expert_pool_routing,
)


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
