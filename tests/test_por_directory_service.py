import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from por.daemon.directory import make_directory_handler
from por.directory import (
    DIRECTORY_SNAPSHOT_VERSION,
    PUBLIC_SNAPSHOT_V1,
    DirectorySnapshot,
    DirectorySnapshotFetchError,
    DirectorySnapshotFormatError,
    DiscoveryRequest,
    PublicManifestDirectory,
    load_public_snapshot_directory,
    load_records_from_snapshot_file,
)
from por.expert_route import PeerObservation, RouteIntent, plan_expert_route
from por.memory_index import IndexConfig, build_memory_index


def _manifest(tmp_path, peer_id, text):
    root = tmp_path / peer_id
    root.mkdir()
    (root / "notes.md").write_text(text, encoding="utf-8")
    return build_memory_index(IndexConfig(peer_id=peer_id, roots=(str(root),))).manifest


def test_directory_snapshot_file_round_trip_preserves_records(tmp_path):
    manifest = _manifest(tmp_path, "peer-art", "Monet Impressionism color light.")
    observation = PeerObservation(peer_id="peer-art", p50_latency_ms=80, price_units=2)
    directory = PublicManifestDirectory.from_manifests(
        [manifest],
        [observation],
        source="test-file-snapshot",
    )

    path = tmp_path / "directory-snapshot.json"
    directory.save_snapshot(path, generated_at="2026-05-30T00:00:00+00:00")

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == DIRECTORY_SNAPSHOT_VERSION
    assert raw["source"] == "test-file-snapshot"
    assert raw["records"][0]["manifest"]["peer_id"] == "peer-art"
    assert raw["records"][0]["observation"]["p50_latency_ms"] == 80

    loaded = load_public_snapshot_directory(path)
    result = loaded.discover(DiscoveryRequest(RouteIntent(prompt="Monet?")))

    assert result.snapshot_size == 1
    assert result.candidates[0].manifest.peer_id == "peer-art"
    assert result.candidates[0].observation == observation


def test_public_snapshot_discovery_does_not_send_exact_query_or_pretruncate(tmp_path):
    weak = _manifest(tmp_path, "peer-systems", "QUIC UDP transport packets.")
    strong = _manifest(
        tmp_path,
        "peer-art",
        "Monet Impressionism painting Paris color light.",
    )
    directory = PublicManifestDirectory.from_manifests([weak, strong])
    path = tmp_path / "directory-snapshot.json"
    DirectorySnapshot.from_directory(directory, generated_at="2026-05-30T00:00:00+00:00").save(path)

    loaded = load_public_snapshot_directory(path)
    intent = RouteIntent(
        prompt="What did Monet change?",
        requested_expertise="Impressionism",
        random_seed=0,
    )
    discovery = loaded.discover(
        DiscoveryRequest(intent, mode=PUBLIC_SNAPSHOT_V1, max_records=1)
    )
    plan = plan_expert_route(intent, discovery.candidates)

    assert discovery.snapshot_size == 2
    assert len(discovery.candidates) == 2
    assert discovery.exact_query_sent is False
    assert discovery.private_query_used is False
    assert "max_records ignored" in discovery.note
    assert plan.selected_peer_id == "peer-art"


def test_load_records_from_snapshot_file(tmp_path):
    manifest = _manifest(tmp_path, "peer-art", "Monet Impressionism color light.")
    path = tmp_path / "directory-snapshot.json"
    PublicManifestDirectory.from_manifests([manifest]).save_snapshot(path)

    records = load_records_from_snapshot_file(path)

    assert len(records) == 1
    assert records[0].peer_id == "peer-art"


def test_public_snapshot_directory_loads_from_http(tmp_path):
    manifest = _manifest(tmp_path, "peer-art", "Monet Impressionism color light.")
    path = tmp_path / "directory-snapshot.json"
    PublicManifestDirectory.from_manifests([manifest]).save_snapshot(path)
    server, thread = _serve_snapshot(path)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/snapshot"

        loaded = load_public_snapshot_directory(url)
        result = loaded.discover(DiscoveryRequest(RouteIntent(prompt="Monet?")))

        assert result.snapshot_size == 1
        assert result.candidates[0].manifest.peer_id == "peer-art"
    finally:
        server.shutdown()
        thread.join(timeout=2.0)
        server.server_close()


def test_http_snapshot_loader_enforces_size_limit(tmp_path):
    manifest = _manifest(tmp_path, "peer-art", "Monet Impressionism color light.")
    path = tmp_path / "directory-snapshot.json"
    PublicManifestDirectory.from_manifests([manifest]).save_snapshot(path)
    server, thread = _serve_snapshot(path)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/snapshot"

        with pytest.raises(DirectorySnapshotFetchError, match="max_bytes"):
            load_public_snapshot_directory(url, max_bytes=10)
    finally:
        server.shutdown()
        thread.join(timeout=2.0)
        server.server_close()


def test_directory_snapshot_rejects_unknown_version(tmp_path):
    path = tmp_path / "directory-snapshot.json"
    path.write_text(
        json.dumps(
            {
                "version": "por.directory_snapshot.v999",
                "generated_at": "2026-05-30T00:00:00+00:00",
                "records": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DirectorySnapshotFormatError):
        load_public_snapshot_directory(path)


def _serve_snapshot(path):
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_directory_handler(path),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
