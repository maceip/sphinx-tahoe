import json
import subprocess
import sys
from urllib.request import Request, urlopen

import pytest

from por.client import ClientRunResult
from por.config import ClusterConfig, DaemonConfig
from por.daemon.client import make_client_http_handler
from por.directory import PublicManifestDirectory
from por.expert_manifest import STATUS_COMPLETED, STATUS_TIMEOUT, VerifiedQualityEvent
from por.quality import (
    DuplicateReviewError,
    QualityEventStore,
    RequestNotCompletedError,
)
from tests.harness import mixnet_harness


def test_quality_store_enforces_completed_request_before_review(tmp_path):
    store = QualityEventStore(tmp_path / "quality.sqlite")
    completed = _event("req-ok", status=STATUS_COMPLETED)
    timed_out = _event("req-timeout", status=STATUS_TIMEOUT)

    store.record_request(completed)
    store.record_request(timed_out)
    review = store.submit_review(request_id="req-ok", rating="great", judge_score=0.9)

    assert review.rating == "great"
    signals = store.aggregate_manifest("manifest-topic-x")
    assert signals.completed_requests == 1
    assert signals.success_rate == 0.5
    assert signals.median_user_rating == 1.0
    assert signals.evaluator_score == 0.9

    with pytest.raises(DuplicateReviewError):
        store.submit_review(request_id="req-ok", rating="great")
    with pytest.raises(RequestNotCompletedError):
        store.submit_review(request_id="req-timeout", rating="wrong")


def test_quality_cli_records_reviews_and_aggregates(tmp_path):
    store_path = tmp_path / "quality.sqlite"
    event_path = tmp_path / "event.json"
    event_path.write_text(_event("req-cli").to_json(), encoding="utf-8")

    record = subprocess.run(
        [
            sys.executable,
            "-m",
            "por",
            "quality",
            "record",
            "--store",
            str(store_path),
            "--event",
            str(event_path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert record.returncode == 0, record.stdout

    review = subprocess.run(
        [
            sys.executable,
            "-m",
            "por",
            "quality",
            "review",
            "--store",
            str(store_path),
            "--request-id",
            "req-cli",
            "--rating",
            "great",
            "--judge-score",
            "0.8",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert review.returncode == 0, review.stdout

    aggregate = subprocess.run(
        [
            sys.executable,
            "-m",
            "por",
            "quality",
            "aggregate",
            "--store",
            str(store_path),
            "--manifest-id",
            "manifest-topic-x",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert aggregate.returncode == 0, aggregate.stdout
    payload = json.loads(aggregate.stdout)
    assert payload["completed_requests"] == 1
    assert payload["median_user_rating"] == 1.0


def test_local_http_review_endpoint_requires_recorded_completed_request(tmp_path):
    store_path = tmp_path / "quality.sqlite"
    daemon = DaemonConfig.from_dict(
        {
            "node_id": "client1",
            "role": "client",
            "client": {
                "local_http": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 0,
                    "path": "/v1/expert",
                    "review_path": "/v1/review",
                    "quality_store_path": str(store_path),
                }
            },
        }
    )
    cluster = ClusterConfig.from_dict(
        {
            "client": {"host": "127.0.0.1", "port": 7000},
            "nodes": {
                "expert_art": {
                    "host": "127.0.0.1",
                    "port": 7001,
                    "kem_pk": "01" * 32,
                    "kem_sk": "02" * 32,
                    "role": "expert",
                }
            },
        }
    )

    def fake_runner(**_kwargs):
        return ClientRunResult(
            selected_peer_id="expert_art",
            degraded_anonymity=False,
            fallback_used=False,
            response_text="expert answer",
            client_logs="client event=fake",
            selected_manifest_id="manifest-topic-x",
            topic="topic X",
        )

    handler = make_client_http_handler(
        daemon=daemon,
        cluster=cluster,
        discovery_provider=PublicManifestDirectory(records=tuple()),
        runner=fake_runner,
    )
    with mixnet_harness() as net:
        server = net.serve_http(handler)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        req = Request(
            f"{base}/v1/expert",
            data=json.dumps({"prompt": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        with urlopen(req, timeout=2.0) as response:
            request_id = _request_id_from_sse(response.read().decode("utf-8"))

        review_req = Request(
            f"{base}/v1/review",
            data=json.dumps({"request_id": request_id, "rating": "great"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(review_req, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["ok"] is True
    assert payload["quality_event"]["request_id"] == request_id
    assert payload["quality_signals"]["completed_requests"] == 1


def _event(request_id, *, status=STATUS_COMPLETED):
    return VerifiedQualityEvent.v0(
        request_id=request_id,
        expert_peer_id="peer-topic-x",
        manifest_id="manifest-topic-x",
        topic="topic X",
        status=status,
        latency_ms=120,
        answer_digest="sha256:" + "ab" * 32,
        timestamp="2026-05-31T07:01:00+00:00",
    )


def _request_id_from_sse(body: str) -> str:
    for block in body.split("\n\n"):
        if block.startswith("event: done\n"):
            data_line = block.splitlines()[1]
            return str(json.loads(data_line.removeprefix("data: "))["request_id"])
    raise AssertionError(body)
