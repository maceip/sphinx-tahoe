"""D1 acceptance test: client reaches NAT'd expert via supernode inline forward.

Proves: client cannot reach expert directly but completes a prompt
through a supernode that forwards packets between them.

Setup:
  - Expert binds on an ephemeral port (simulating NAT — client doesn't know it)
  - Supernode binds on a known port (public IP equivalent)
  - Expert registers with supernode via PeerAddressRelay
  - Client dials supernode endpoint from PeerAddressRecord
  - Supernode forwards packets inline to expert
  - Expert processes forward packet, streams circuit reply back via supernode
  - Client receives circuit stream through supernode
"""

import json
import os
import socket
import time
from os import urandom

from sphinxmix.OutfoxClient import packet_create
from sphinxmix.OutfoxNode import (
    circuit_packet_create, circuit_packet_decrypt, circuit_packet_process,
    outfox_process,
)
from sphinxmix.OutfoxParams import OutfoxParams, derive_circuit_key

from por.peer_address import (
    PeerAddressRelay, UdpEndpoint, AddressExposurePolicy,
    build_dial_plan, ROUTE_RELAY,
)
from por.supernode import SupernodeForwarder
from por.node_runtime import build_native_forward_plan
from por.wire_frame import encode_forward, decode_datagram, CIRCUIT, FORWARD


def test_supernode_inline_forward():
    """Client reaches expert through supernode — no direct connection."""
    params = OutfoxParams(payload_size=2048, routing_size=16, max_hops=5)

    # Generate keys
    expert_pk, expert_sk = params.kem.keygen()
    supernode_pk, supernode_sk = params.kem.keygen()

    # Bind sockets
    expert_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    expert_sock.bind(("127.0.0.1", 0))
    expert_sock.settimeout(1.0)
    expert_addr = expert_sock.getsockname()

    supernode_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    supernode_sock.bind(("127.0.0.1", 0))
    supernode_sock.settimeout(1.0)
    supernode_addr = supernode_sock.getsockname()

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_sock.bind(("127.0.0.1", 0))
    client_sock.settimeout(1.0)
    client_addr = client_sock.getsockname()

    # Expert registers with supernode
    relay = PeerAddressRelay(
        relay_id="supernode",
        relay_endpoint=UdpEndpoint(*supernode_addr),
        secret=urandom(32),
    )
    challenge = relay.request_registration(
        peer_id="expert_art",
        observed_endpoint=UdpEndpoint(*expert_addr),
    )
    record = relay.confirm_registration(challenge)
    assert not record.is_expired()

    # Supernode forwarder tracks expert
    forwarder = SupernodeForwarder(relay)
    forwarder.register_peer("expert_art", expert_addr)

    # Client builds dial plan from record — gets supernode endpoint
    plan = build_dial_plan(record)
    assert plan.contactable
    assert plan.primary.kind == ROUTE_RELAY
    dial_endpoint = plan.primary.endpoint
    assert dial_endpoint.as_tuple() == supernode_addr

    # Client builds forward packet: supernode (relay) → expert (exit)
    forward_path = ["supernode", "expert_art"]
    route_infos, circuit_setup, client_peel_keys = build_native_forward_plan(
        tuple(forward_path))
    kem_keys = [supernode_pk, expert_pk]
    message = b'{"prompt": "What did Monet change?"}'

    header, payload = packet_create(
        params, route_infos, kem_keys, message, circuit_setup=circuit_setup)

    # Client sends to supernode (NOT to expert directly)
    client_sock.sendto(encode_forward(header, payload), supernode_addr)

    # === Supernode receives and processes as relay ===
    data, sender_addr = supernode_sock.recvfrom(65535)
    kind, body_a, body_b = decode_datagram(data, params.payload_size)
    assert kind == "forward"

    # Supernode processes its Outfox layer (it's a relay hop)
    circuits = {}
    def on_circ(icid, ck, nh, ocid, ttl):
        circuits["inbound"] = icid.hex()
        circuits["key"] = ck.hex()
        circuits["outbound"] = ocid.hex()
        circuits["next_hop"] = nh.rstrip(b'\x00').decode('ascii', errors='replace')

    result = outfox_process(params, supernode_sk, supernode_pk,
                            (body_a, body_b), is_last=False, on_circuit=on_circ)
    assert result is not None
    routing, _flag, (next_header, next_payload) = result
    next_id = routing.rstrip(b'\x00').decode('ascii', errors='replace')
    assert next_id == "expert_art"

    # Supernode forwards to expert via forwarder lookup
    peer_addr = forwarder.lookup_peer_addr("expert_art")
    assert peer_addr is not None
    supernode_sock.sendto(encode_forward(next_header, next_payload), peer_addr)

    # === Expert receives forward packet ===
    data, from_addr = expert_sock.recvfrom(65535)
    kind, body_a, body_b = decode_datagram(data, params.payload_size)
    assert kind == "forward"

    expert_circuits = {}
    def on_circ_expert(icid, ck, nh, ocid, ttl):
        expert_circuits["inbound"] = icid.hex()
        expert_circuits["key"] = ck.hex()
        expert_circuits["outbound"] = ocid.hex()
        expert_circuits["next_hop"] = nh.rstrip(b'\x00').decode('ascii', errors='replace')

    result = outfox_process(params, expert_sk, expert_pk,
                            (body_a, body_b), is_last=True, on_circuit=on_circ_expert)
    assert result is not None
    _, _, msg, _ = result
    assert b"Monet" in msg

    # Expert streams reply via circuit packet back through supernode
    exit_key = bytes.fromhex(expert_circuits["key"])
    exit_outbound = bytes.fromhex(expert_circuits["outbound"])
    reply_data = json.dumps({"seq": 0, "data": "Monet changed everything", "done": False}).encode()
    circuit_pkt = circuit_packet_create(params, exit_outbound, 1, reply_data, [exit_key])

    # Expert sends circuit packet to supernode (return_next)
    expert_sock.sendto(circuit_pkt, supernode_addr)

    # === Supernode receives circuit packet, processes relay layer ===
    data, _ = supernode_sock.recvfrom(65535)
    assert data[0:1] == CIRCUIT

    inbound_cid = data[1:17].hex()
    assert inbound_cid == circuits["inbound"]
    relay_key = bytes.fromhex(circuits["key"])
    outbound_cid = bytes.fromhex(circuits["outbound"])
    processed = circuit_packet_process(params, relay_key, data, outbound_link_cid=outbound_cid)
    assert processed is not None
    _, _, forwarded = processed

    # Supernode forwards circuit packet to client
    supernode_sock.sendto(forwarded, client_addr)

    # === Client receives circuit packet ===
    data, _ = client_sock.recvfrom(65535)
    assert data[0:1] == CIRCUIT

    plain = circuit_packet_decrypt(params, client_peel_keys, data)
    assert plain is not None
    chunk = json.loads(plain.decode("utf-8"))
    assert chunk["data"] == "Monet changed everything"

    # Send done
    done_data = json.dumps({"seq": 1, "data": "", "done": True}).encode()
    done_pkt = circuit_packet_create(params, exit_outbound, 2, done_data, [exit_key])
    expert_sock.sendto(done_pkt, supernode_addr)

    data, _ = supernode_sock.recvfrom(65535)
    processed = circuit_packet_process(params, relay_key, data, outbound_link_cid=outbound_cid)
    _, _, forwarded = processed
    supernode_sock.sendto(forwarded, client_addr)

    data, _ = client_sock.recvfrom(65535)
    plain = circuit_packet_decrypt(params, client_peel_keys, data)
    done = json.loads(plain.decode("utf-8"))
    assert done["done"] is True

    # Cleanup
    expert_sock.close()
    supernode_sock.close()
    client_sock.close()

    print("[PASS] D1: Client reached NAT'd expert via supernode inline forward.")


def test_supernode_heartbeat_expiry():
    """Expired peer becomes unreachable."""
    relay = PeerAddressRelay(
        relay_id="supernode",
        relay_endpoint=UdpEndpoint("127.0.0.1", 9999),
        secret=urandom(32),
        ttl_seconds=1,
    )
    forwarder = SupernodeForwarder(relay, ttl=1)
    forwarder.register_peer("expert_art", ("127.0.0.1", 8888))
    assert forwarder.lookup_peer_addr("expert_art") is not None

    time.sleep(1.1)
    assert forwarder.lookup_peer_addr("expert_art") is None

    print("[PASS] D2: Expired peer unreachable after TTL.")
