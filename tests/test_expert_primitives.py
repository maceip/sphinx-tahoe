import json
from pathlib import Path

import pytest

from por.client import run_client_once
from por.config import ClusterConfig
from por.directory import DirectorySnapshot, DiscoveryRequest, PublicManifestDirectory
from por.expert_manifest import (
    CAPABILITY_EXPERT_SESSION,
    ENGINE_CLAUDE_CODE,
    ExpertQualitySignals,
    ExpertSessionManifest,
    VerifiedQualityEvent,
)
from por.expert_route import RouteIntent, plan_expert_route
from por.memory_index import IndexConfig, build_memory_index
from tests.test_por_client import _write_cluster


GOLDEN_DIR = Path(__file__).parent / "golden_assets"


def test_golden_expert_session_manifest_round_trips():
    raw = json.loads((GOLDEN_DIR / "expert_session_manifest.v0.json").read_text(encoding="utf-8"))

    manifest = ExpertSessionManifest.from_dict(raw)

    assert manifest.version == "tenet.expert_manifest.v0"
    assert manifest.capability_type == CAPABILITY_EXPERT_SESSION
    assert manifest.engine == ENGINE_CLAUDE_CODE
    assert manifest.quality_signals.reputation_weight() > 0.75
    assert json.loads(manifest.to_json()) == raw


def test_golden_verified_quality_event_round_trips():
    raw = json.loads((GOLDEN_DIR / "verified_quality_event.v0.json").read_text(encoding="utf-8"))

    event = VerifiedQualityEvent.from_dict(raw)

    assert event.version == "tenet.quality_event.v0"
    assert event.status == "completed"
    assert event.rating == "great"
    assert json.loads(event.to_json()) == raw


def test_quality_event_rejects_unverified_rating_without_completed_request():
    raw = json.loads((GOLDEN_DIR / "verified_quality_event.v0.json").read_text(encoding="utf-8"))
    raw["rating"] = "brigade"

    with pytest.raises(ValueError, match="unsupported rating"):
        VerifiedQualityEvent.from_dict(raw)


def test_directory_snapshot_round_trips_expert_session_manifest(tmp_path):
    memory_manifest = _memory_manifest(tmp_path, "peer-topic-x", "placeholder corpus", publish_terms=False)
    expert_manifest = _expert_manifest("peer-topic-x")
    path = tmp_path / "snapshot.json"

    PublicManifestDirectory.from_manifests(
        [memory_manifest],
        expert_manifests=[expert_manifest],
    ).save_snapshot(path, generated_at="2026-05-31T07:00:00+00:00")

    loaded = DirectorySnapshot.load(path)
    record = loaded.records[0]

    assert record.expert_manifest == expert_manifest
    assert record.candidate().expert_manifest == expert_manifest


def test_route_planner_can_select_expert_session_without_public_terms(tmp_path):
    memory_manifest = _memory_manifest(tmp_path, "peer-topic-x", "unpublished private corpus", publish_terms=False)
    expert_manifest = _expert_manifest("peer-topic-x")
    directory = PublicManifestDirectory.from_manifests(
        [memory_manifest],
        expert_manifests=[expert_manifest],
    )

    intent = RouteIntent(
        prompt="How should we route questions to a compiled Claude expert session?",
        requested_expertise="topic X expert session routing",
        min_pool_size=1,
    )
    discovery = directory.discover(request=DiscoveryRequest(intent))
    plan = plan_expert_route(intent, discovery.candidates)

    assert plan.use_expert
    assert plan.selected_peer_id == "peer-topic-x"
    assert plan.selected_capability_type == CAPABILITY_EXPERT_SESSION
    assert plan.selected_engine == ENGINE_CLAUDE_CODE
    assert plan.pool.candidates[0].session_score > 0
    assert plan.pool.candidates[0].memory_score == 0


def test_client_envelope_advertises_selected_expert_session(monkeypatch, tmp_path):
    config_path, _harness, _node_ids = _write_cluster(tmp_path, node_count=3)
    cluster = ClusterConfig.load(config_path)
    memory_manifest = _memory_manifest(tmp_path, "expert_art", "unpublished private corpus", publish_terms=False)
    expert_manifest = _expert_manifest("expert_art")
    directory = PublicManifestDirectory.from_manifests(
        [memory_manifest],
        expert_manifests=[expert_manifest],
    )
    seen = {}

    def fake_send_prepared_envelope(**kwargs):
        seen["envelope"] = kwargs["envelope"]
        return "[fake expert-session response]", ["client event=fake_stream"]

    monkeypatch.setattr("por.client.send_prepared_envelope", fake_send_prepared_envelope)

    result = run_client_once(
        cluster=cluster,
        discovery_provider=directory,
        prompt="How should topic X expert sessions answer routed prompts?",
        requested_expertise="topic X expert session routing",
        relay_path=("relay1",),
        random_seed=1,
    )

    provider_request = seen["envelope"].provider_request
    assert result.fallback_used is False
    assert provider_request["provider"] == "expert_peer"
    assert provider_request["capability_type"] == CAPABILITY_EXPERT_SESSION
    assert provider_request["engine"] == ENGINE_CLAUDE_CODE


def _memory_manifest(tmp_path, peer_id, text, *, publish_terms=True):
    root = tmp_path / peer_id
    root.mkdir(exist_ok=True)
    (root / "notes.md").write_text(text, encoding="utf-8")
    return build_memory_index(
        IndexConfig(peer_id=peer_id, roots=(str(root),), publish_terms=publish_terms)
    ).manifest


def _expert_manifest(peer_id):
    return ExpertSessionManifest.v0(
        peer_id=peer_id,
        manifest_id=f"{peer_id}-session-manifest",
        engine=ENGINE_CLAUDE_CODE,
        topics=("topic X", "expert session routing", "compiled Claude Codex context"),
        summary="Compiled Claude Code expert session with papers, tools, and session policy.",
        answer_policy="grounded",
        freshness="2026-05-31T07:00:00+00:00",
        quality_signals=ExpertQualitySignals(
            completed_requests=20,
            success_rate=0.95,
            median_user_rating=0.90,
            evaluator_score=0.88,
        ),
    )
