"""End-to-end mixnet simulator tests.

Tests the full P-OR data path: packet creation → forward routing →
exit processing → reply → sender decryption. No network — direct calls.
"""

import struct
from sphinxmix.mixnet import MixnetSim, Client
from sphinxmix.OutfoxParams import (
    FLAG_REAL, FLAG_DUMMY, verify_payload, generate_signing_keypair,
)
from sphinxmix.OutfoxClient import surb_use, surb_check, surb_recover


def test_forward_through_network():
    """Full forward packet through 5 nodes."""
    sim = MixnetSim(num_nodes=8)
    client = sim.create_client(b"alice")

    path = sim.node_ids()[:5]
    header, payload = client.create_forward(path, b"hello mixnet")

    result = sim.route_forward(path, header, payload)
    assert result is not None
    routing, flag, msg, surb_info = result
    assert msg == b"hello mixnet"
    assert flag == FLAG_REAL
    assert surb_info is None

    print("[PASS] Forward: 5-hop delivery through simulated network.")


def test_repliable_round_trip():
    """Full repliable flow: forward → exit → reply → sender decrypts."""
    sim = MixnetSim(num_nodes=8)
    client = sim.create_client(b"alice")

    fwd_path = sim.node_ids()[:4]
    rply_relays = sim.node_ids()[4:7]

    header, payload = client.create_repliable(
        fwd_path, rply_relays, b"please reply")

    result = sim.route_forward(fwd_path, header, payload)
    assert result is not None
    routing, flag, msg, surb_info = result
    assert msg == b"please reply"
    assert surb_info is not None

    surb_header, surb_key = surb_info

    reply_header, reply_payload = surb_use(
        sim.params, (surb_header, surb_key), b"here is your reply")

    reply_header, reply_payload = sim.route_reply(
        rply_relays, reply_header, reply_payload)
    assert reply_header is not None

    received = client.receive_reply(reply_header, reply_payload)
    assert received == b"here is your reply"

    print("[PASS] Repliable: full round-trip forward + reply through network.")


def test_signed_message():
    """Forward packet with ML-DSA-65 signature verified at exit."""
    sim = MixnetSim(num_nodes=8, payload_size=4096)
    client = sim.create_client(b"alice")

    path = sim.node_ids()[:3]
    receiver_id = b"bob_id_endpoint"
    header, payload = client.create_signed(
        path, receiver_id, b"signed prompt")

    result = sim.route_forward(path, header, payload)
    assert result is not None
    routing, flag, msg, _ = result

    sig_len = struct.unpack(">H", msg[:2])[0]
    signature = msg[2:2 + sig_len]
    signed_content = msg[2 + sig_len:]

    assert verify_payload(client.sign_pk, signed_content, signature)
    assert b"signed prompt" in signed_content
    assert client.client_id in signed_content
    assert receiver_id in signed_content

    print("[PASS] Signed: ML-DSA-65 signature verified at exit node.")


def test_dummy_traffic():
    """Dummy packets are processed identically but flagged."""
    sim = MixnetSim(num_nodes=8)
    client = sim.create_client(b"alice")

    path = sim.node_ids()[:3]

    real_h, real_p = client.create_forward(path, b"real message")
    dummy_h, dummy_p = client.create_dummy(path)

    real_result = sim.route_forward(path, real_h, real_p)
    dummy_result = sim.route_forward(path, dummy_h, dummy_p)

    assert real_result is not None
    assert dummy_result is not None

    _, real_flag, _, _ = real_result
    _, dummy_flag, _, _ = dummy_result
    assert real_flag == FLAG_REAL
    assert dummy_flag == FLAG_DUMMY

    print("[PASS] Dummy: real and dummy packets processed identically, flags differ.")


def test_multiple_clients():
    """Multiple clients routing through the same network simultaneously."""
    sim = MixnetSim(num_nodes=8)
    alice = sim.create_client(b"alice")
    bob = sim.create_client(b"bob__")
    carol = sim.create_client(b"carol")

    path = sim.node_ids()[:4]
    msgs = [
        (alice, b"alice's message"),
        (bob, b"bob's message"),
        (carol, b"carol's message"),
    ]

    for client, msg in msgs:
        h, p = client.create_forward(path, msg)
        result = sim.route_forward(path, h, p)
        assert result is not None
        _, _, received, _ = result
        assert received == msg

    stats = sim.stats()
    assert stats["forward"] == 4 * 3

    print(f"[PASS] Multi-client: 3 clients, {stats['forward']} hops total.")


def test_tampered_header_rejected():
    """Tampered header fails AEAD at the first honest node."""
    sim = MixnetSim(num_nodes=8)
    client = sim.create_client(b"alice")

    path = sim.node_ids()[:3]
    header, payload = client.create_forward(path, b"test")

    tampered = bytearray(header)
    tampered[40] ^= 0xFF

    try:
        sim.route_forward(path, bytes(tampered), payload)
        assert False, "Should have failed"
    except ValueError:
        pass

    print("[PASS] Tampered header: AEAD rejection at first hop.")


def test_tagged_payload_rejected():
    """Tagged payload detected at exit via zero-padding check."""
    sim = MixnetSim(num_nodes=8)
    client = sim.create_client(b"alice")

    path = sim.node_ids()[:3]
    header, payload = client.create_forward(path, b"secret")

    tagged = bytearray(payload)
    tagged[50] ^= 0xFF

    result = sim.route_forward(path, header, bytes(tagged))
    assert result is None

    print("[PASS] Tagged payload: PRP destroys contents, exit rejects.")


def test_circuit_table():
    """Circuit key table: store, lookup, expiry."""
    from sphinxmix.mixnet import CircuitTable

    table = CircuitTable(ttl=1)
    cid = b"circuit_id_12345"
    key = b"symmetric_key!!!"

    table.store(cid, key)
    assert table.lookup(cid) == key
    assert table.size() == 1

    import time
    time.sleep(1.1)
    assert table.lookup(cid) is None
    assert table.size() == 0

    print("[PASS] Circuit table: store, lookup, TTL expiry.")


def test_network_stats():
    """Node statistics are tracked correctly."""
    sim = MixnetSim(num_nodes=4)
    client = sim.create_client(b"alice")

    path = sim.node_ids()[:4]
    for _ in range(10):
        h, p = client.create_forward(path, b"msg")
        sim.route_forward(path, h, p)

    stats = sim.stats()
    assert stats["forward"] == 40

    print(f"[PASS] Stats: {stats['forward']} forward hops across 10 messages.")


if __name__ == "__main__":
    print("=" * 60)
    print("P-OR Mixnet Simulator Tests")
    print("=" * 60)
    print()

    test_forward_through_network()
    test_repliable_round_trip()
    test_signed_message()
    test_dummy_traffic()
    test_multiple_clients()
    test_tampered_header_rejected()
    test_tagged_payload_rejected()
    test_circuit_table()
    test_network_stats()

    print()
    print("=" * 60)
    print("ALL MIXNET TESTS PASSED")
    print("=" * 60)
