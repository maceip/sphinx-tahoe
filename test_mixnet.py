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


def test_exit_node_discovery():
    """Clients find exit nodes by provider capability."""
    providers = {
        3: [{"name": "anthropic", "models": ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"]}],
        5: [{"name": "anthropic", "models": ["claude-sonnet-4-20250514"]},
            {"name": "openai", "models": ["gpt-4o"]}],
        7: [{"name": "openai", "models": ["gpt-4o", "gpt-4o-mini"]}],
    }
    sim = MixnetSim(num_nodes=8, node_providers=providers)
    client = sim.create_client(b"alice")

    # Find Anthropic exit nodes
    anthropic_exits = sim.pki.find_exit_nodes(provider="anthropic")
    assert len(anthropic_exits) == 2
    assert sim.node_ids()[3] in anthropic_exits
    assert sim.node_ids()[5] in anthropic_exits

    # Find OpenAI exit nodes
    openai_exits = sim.pki.find_exit_nodes(provider="openai")
    assert len(openai_exits) == 2
    assert sim.node_ids()[5] in openai_exits
    assert sim.node_ids()[7] in openai_exits

    # Find by specific model
    haiku_exits = sim.pki.find_exit_nodes(provider="anthropic", model="claude-haiku-4-5-20251001")
    assert len(haiku_exits) == 1
    assert sim.node_ids()[3] in haiku_exits

    # No exit for unknown provider
    assert sim.pki.find_exit_nodes(provider="deepseek") == []

    print("[PASS] Exit discovery: find nodes by provider and model.")


def test_capability_based_routing():
    """Client auto-selects path based on desired provider."""
    providers = {
        4: [{"name": "anthropic", "models": ["claude-sonnet-4-20250514"]}],
        6: [{"name": "openai", "models": ["gpt-4o"]}],
    }
    sim = MixnetSim(num_nodes=8, node_providers=providers)
    client = sim.create_client(b"alice")

    # Select path for Anthropic — exit must be node 4
    path = client.select_path(provider="anthropic", num_hops=3)
    assert path[-1] == sim.node_ids()[4]
    assert len(path) == 3

    # Select path for OpenAI — exit must be node 6
    path = client.select_path(provider="openai", num_hops=3)
    assert path[-1] == sim.node_ids()[6]
    assert len(path) == 3

    # Route a message through the auto-selected path
    path = client.select_path(provider="anthropic", num_hops=3)
    header, payload = client.create_forward(path, b"test prompt")
    result = sim.route_forward(path, header, payload)
    assert result is not None
    _, _, msg, _ = result
    assert msg == b"test prompt"

    # No provider available
    try:
        client.select_path(provider="nonexistent")
        assert False
    except ValueError:
        pass

    print("[PASS] Capability routing: auto-select exit by provider, route works.")


def test_exit_with_api_call():
    """Exit node selected by capability makes the actual LLM call."""
    providers = {
        2: [{"name": "anthropic", "models": ["claude-sonnet-4-20250514"],
             "api_base": "http://127.0.0.1:8000"}],
    }
    sim = MixnetSim(num_nodes=6, payload_size=32768, node_providers=providers)
    client = sim.create_client(b"alice")

    import json
    from urllib.request import Request, urlopen

    path = client.select_path(provider="anthropic", num_hops=3)
    request_body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "say ok"}],
    }).encode()

    fwd_path = path
    rply_relays = [nid for nid in sim.node_ids() if nid not in path][:2]
    header, payload = client.create_repliable(fwd_path, rply_relays, request_body)

    result = sim.route_forward(fwd_path, header, payload)
    assert result is not None
    routing, flag, msg, surb_info = result
    assert msg == request_body

    exit_node = sim.nodes[path[-1]]
    api_base = exit_node.providers[0]["api_base"]
    req = Request(api_base + "/v1/messages", data=msg, method="POST", headers={
        "Content-Type": "application/json",
        "x-api-key": "none",
        "anthropic-version": "2023-06-01",
    })
    resp = urlopen(req, timeout=30)
    resp_body = resp.read()
    assert resp.status == 200

    surb_header, surb_key = surb_info
    from sphinxmix.OutfoxClient import surb_use
    reply_header, reply_payload = surb_use(sim.params, (surb_header, surb_key), resp_body)
    reply_header, reply_payload = sim.route_reply(rply_relays, reply_header, reply_payload)
    decrypted = client.receive_reply(reply_header, reply_payload)
    assert decrypted == resp_body

    print(f"[PASS] Exit with API: capability-selected exit called LLM, response verified.")


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
    test_exit_node_discovery()
    test_capability_based_routing()
    test_exit_with_api_call()
    test_network_stats()

    print()
    print("=" * 60)
    print("ALL MIXNET TESTS PASSED")
    print("=" * 60)
