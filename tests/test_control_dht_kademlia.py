"""Tests for the hardened Kademlia control overlay (Item 3).

Unit tests cover publish status / capacity bounds / metrics / peer scoring.
Integration tests (real UDP nodes) cover publish→fetch, restart republish, and —
the headline fix — that stop() drains cleanly and leaves no pending asyncio task.
"""

from __future__ import annotations

import socket
import time

import pytest
from nacl.signing import SigningKey

from tenet.mixnet.control.kademlia_overlay import (
    DhtMetrics,
    KademliaControlOverlay,
    PeerFailureScore,
    PUBLISH_REJECTED_MAX_RECORDS,
    PUBLISH_REJECTED_OVERSIZED,
    PUBLISH_SCHEDULED,
)
from tenet.mixnet.control.records import (
    MAX_SIGNED_CONTROL_RECORD_BYTES,
    ControlRecord,
    RECORD_TYPE_TRUST_POINTER,
    sign_control_record,
)


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _signed(key="trust/pointer", *, value=None, seq=1):
    sk = SigningKey.generate()
    record = ControlRecord(
        network_id="net", key=key, record_type=RECORD_TYPE_TRUST_POINTER,
        seq=seq, issued_at=1000.0, expires_at=1000.0 + 1e9,
        value=value if value is not None else {"ok": "1"},
    )
    return sign_control_record(record, signing_key_hex=sk.encode().hex(), key_id="root")


# --------------------------------------------------------------------------- #
# unit: peer scoring + metrics
# --------------------------------------------------------------------------- #


def test_peer_failure_scoring():
    p = PeerFailureScore()
    assert p.score("n1") == 0
    p.record_failure("n1")
    p.record_failure("n1")
    assert p.score("n1") == 2
    assert p.is_suspect("n1", threshold=2)
    p.record_success("n1")
    assert p.score("n1") == 0
    assert not p.is_suspect("n1", threshold=2)


def test_metrics_snapshot_is_plain_dict():
    m = DhtMetrics()
    m.publishes_scheduled += 1
    snap = m.snapshot()
    assert snap["publishes_scheduled"] == 1
    assert isinstance(snap, dict)


# --------------------------------------------------------------------------- #
# integration: real single/multi node behaviour
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_publish_oversized_rejected_on_started_node():
    overlay = KademliaControlOverlay("a", listen_port=_free_udp_port(), network_id="net")
    overlay.start()
    try:
        assert overlay.wait_for_mesh(timeout=5.0)
        big = _signed(value={"blob": "x" * (MAX_SIGNED_CONTROL_RECORD_BYTES + 1000)})
        assert overlay.publish("trust/big", big) == PUBLISH_REJECTED_OVERSIZED
        assert overlay.metrics.publishes_rejected == 1
        assert overlay.owned_record_count() == 0
    finally:
        overlay.stop()


@pytest.mark.integration
def test_publish_max_records_rejected():
    overlay = KademliaControlOverlay("a", listen_port=_free_udp_port(), network_id="net", max_records=2)
    overlay.start()
    try:
        assert overlay.wait_for_mesh(timeout=5.0)
        assert overlay.publish("k1", _signed(key="k1")) == PUBLISH_SCHEDULED
        assert overlay.publish("k2", _signed(key="k2")) == PUBLISH_SCHEDULED
        assert overlay.publish("k3", _signed(key="k3")) == PUBLISH_REJECTED_MAX_RECORDS
        # updating an existing owned key is still allowed
        assert overlay.publish("k1", _signed(key="k1", seq=2)) == PUBLISH_SCHEDULED
    finally:
        overlay.stop()


@pytest.mark.integration
def test_stop_leaves_no_pending_tasks():
    overlay = KademliaControlOverlay("a", listen_port=_free_udp_port(), network_id="net")
    overlay.start()
    assert overlay.wait_for_mesh(timeout=5.0)
    for i in range(5):
        assert overlay.publish(f"k{i}", _signed(key=f"k{i}")) == PUBLISH_SCHEDULED
    overlay.stop()
    # The serving coroutine drained on shutdown.
    assert overlay.is_running is False
    assert overlay._inflight == set()
    assert overlay._thread is not None and not overlay._thread.is_alive()


@pytest.mark.integration
def test_publish_fetch_roundtrip_two_nodes():
    a_port = _free_udp_port()
    node_a = KademliaControlOverlay("a", listen_port=a_port, network_id="net")
    node_b = KademliaControlOverlay("b", listen_port=_free_udp_port(), network_id="net")
    node_a.start()
    assert node_a.wait_for_mesh(timeout=5.0)
    node_b.start(bootstrap=[("127.0.0.1", a_port)])
    assert node_b.wait_for_mesh(timeout=5.0)
    try:
        signed = _signed(key="pool/soup/descriptor")
        assert node_b.publish("pool/soup/descriptor", signed) == PUBLISH_SCHEDULED
        node_b.flush(timeout=5.0)
        # allow replication to settle, then fetch from the other node
        got = None
        for _ in range(10):
            got = node_a.fetch("pool/soup/descriptor", timeout=2.0)
            if got is not None:
                break
            time.sleep(0.3)
        assert got is not None
        assert got.record.key == "pool/soup/descriptor"
        assert node_a.metrics.fetch_hits >= 1
    finally:
        node_b.stop()
        node_a.stop()


@pytest.mark.integration
def test_restart_republishes_owned_records():
    # Restart on the same object: owned records must be re-asserted after mesh
    # readiness. A fresh port is used on restart to avoid racing the OS release
    # of the prior UDP bind (the republish is driven by the owned set on the
    # object, not by the port).
    node = KademliaControlOverlay("b", listen_port=_free_udp_port(), network_id="net")
    node.start()
    assert node.wait_for_mesh(timeout=5.0)
    try:
        node.publish("pool/ramen/descriptor", _signed(key="pool/ramen/descriptor"))
        node.flush(timeout=5.0)
        assert node.owned_record_count() == 1
        scheduled_before = node.metrics.publishes_scheduled

        node.stop()
        node.listen_port = _free_udp_port()
        node.start()
        assert node.wait_for_mesh(timeout=5.0)
        for _ in range(10):
            if node.metrics.publishes_scheduled > scheduled_before:
                break
            time.sleep(0.2)
        assert node.metrics.publishes_scheduled > scheduled_before
        assert node.owned_record_count() == 1
    finally:
        node.stop()
