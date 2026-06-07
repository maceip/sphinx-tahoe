"""Tests for control anti-entropy sync (Item 4)."""

from __future__ import annotations

from nacl.signing import SigningKey

from tenet.mixnet.control.descriptors import ExpertDescriptor
from tenet.mixnet.control.live_sync import (
    SYNC_SOURCE,
    dht_discovered_control_contacts,
    ingest_sync_records,
)
from tenet.mixnet.control.records import sign_control_record
from tenet.mixnet.control.service import MixnetControlService
from tenet.mixnet.control.sync_state import ControlSyncState, PeerSyncHealth

POOL = "monet.expert~tenet"


def _service():
    sk = SigningKey.generate()
    return MixnetControlService(network_id="net", verify_keys={"root": sk.verify_key.encode().hex()}), sk


def _expert_record_dict(svc, sk, *, seq=1, key_id="root", signer=None):
    expert = ExpertDescriptor(expert_id="e", pools=(POOL,), manifest_ref="m")
    unsigned = svc.make_unsigned_expert_descriptor(expert, seq=seq)
    signing = (signer or sk).encode().hex()
    return sign_control_record(unsigned, signing_key_hex=signing, key_id=key_id).to_dict()


# --------------------------------------------------------------------------- #
# ingestion: forged / stale / valid
# --------------------------------------------------------------------------- #


def test_ingest_rejects_forged_record():
    svc, sk = _service()
    # signed by a different key but claiming key_id "root" -> signature invalid
    forged_signer = SigningKey.generate()
    raw = _expert_record_dict(svc, sk, signer=forged_signer)
    outcome = ingest_sync_records(svc, [raw])
    assert outcome.stored == 0
    assert outcome.rejected == 1
    assert svc.get("expert/e/descriptor") is None


def test_ingest_rejects_stale_seq():
    svc, sk = _service()
    svc.put_signed(sign_control_record(
        svc.make_unsigned_expert_descriptor(ExpertDescriptor(expert_id="e", pools=(POOL,), manifest_ref="m"), seq=5),
        signing_key_hex=sk.encode().hex(), key_id="root",
    ))
    stale = _expert_record_dict(svc, sk, seq=3)
    outcome = ingest_sync_records(svc, [stale])
    assert outcome.stored == 0 and outcome.rejected == 1


def test_ingest_stores_valid_with_sync_source():
    svc, sk = _service()
    outcome = ingest_sync_records(svc, [_expert_record_dict(svc, sk, seq=1)])
    assert outcome.stored == 1 and outcome.rejected == 0
    assert svc.record_source("expert/e/descriptor") == SYNC_SOURCE


def test_ingest_handles_non_objects():
    svc, _sk = _service()
    outcome = ingest_sync_records(svc, ["not-a-dict", 42, None])
    assert outcome.stored == 0 and outcome.rejected == 3
    assert "not_an_object" in outcome.reasons


# --------------------------------------------------------------------------- #
# cursor persistence
# --------------------------------------------------------------------------- #


def test_cursor_persistence_roundtrip(tmp_path):
    path = tmp_path / "sync-state.json"
    state = ControlSyncState.load(path)
    state.set_cursor("pool/", "pool/zzz")
    state.mark_refreshed("pool/", now=1000.0)
    state.record_peer_failure("peerA", now=1000.0)
    state.save()

    reloaded = ControlSyncState.load(path)
    assert reloaded.cursor("pool/") == "pool/zzz"
    assert reloaded.last_refresh["pool/"] == 1000.0
    assert reloaded.peers["peerA"].failures == 1
    assert reloaded.peers["peerA"].next_retry_after > 1000.0


# --------------------------------------------------------------------------- #
# peer backoff + refresh interval
# --------------------------------------------------------------------------- #


def test_peer_backoff_is_exponential_and_resets():
    state = ControlSyncState()
    assert state.peer_available("p", now=0.0)  # unknown peer is available
    state.record_peer_failure("p", now=100.0, base_backoff=1.0)
    assert not state.peer_available("p", now=100.5)  # backed off
    assert state.peer_available("p", now=101.5)  # 1s backoff elapsed
    state.record_peer_failure("p", now=200.0, base_backoff=1.0)  # 2nd failure -> 2s
    assert not state.peer_available("p", now=201.5)
    assert state.peer_available("p", now=202.5)
    state.record_peer_success("p")
    assert state.peer_available("p", now=202.6)
    assert state.peers["p"].failures == 0


def test_refresh_interval_gating():
    state = ControlSyncState()
    assert state.due("pool/", interval=60.0, now=1000.0)  # never refreshed
    state.mark_refreshed("pool/", now=1000.0)
    assert not state.due("pool/", interval=60.0, now=1030.0)  # too soon
    assert state.due("pool/", interval=60.0, now=1061.0)  # interval elapsed


# --------------------------------------------------------------------------- #
# DHT-discovered control peers
# --------------------------------------------------------------------------- #


class _FakeOverlay:
    def control_wire_contacts(self, *, limit=20):
        return (("kad:abc", ("10.0.0.7", 7001)), ("kad:def", ("10.0.0.8", 7001)))


def test_dht_discovered_control_contacts():
    svc, _sk = _service()
    assert dht_discovered_control_contacts(svc) == ()  # no overlay attached
    svc._kademlia_overlay = _FakeOverlay()
    contacts = dht_discovered_control_contacts(svc)
    assert ("kad:abc", ("10.0.0.7", 7001)) in contacts
    assert len(contacts) == 2
