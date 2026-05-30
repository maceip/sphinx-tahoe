"""T1+T2 transport tests: REACH registration over UDP + opaque forward loop.

Proves: expert registers via REACH_REGISTER → REACH_CONFIRM, then client
sends Outfox forward through supernode, expert receives it, and reply
circuit packets flow back through supernode to client.

No static expert IP in client config — supernode is the only endpoint.
"""

import json
import socket
import time
from os import urandom

from sphinxmix.OutfoxClient import packet_create
from sphinxmix.OutfoxNode import (
    circuit_packet_create, circuit_packet_decrypt, circuit_packet_process,
    outfox_process,
)
from sphinxmix.OutfoxParams import OutfoxParams

from por.daemon.supernode import SupernodeDaemon
from por.node_runtime import WireNodeRuntime, build_native_forward_plan
from por.peer_address import PeerAddressRelay, UdpEndpoint
from por.reach_wire import (
    encode_register, encode_confirm, decode_reach_datagram,
    REACH_CHALLENGE,
)
from por.wire_frame import encode_forward, decode_datagram, CIRCUIT


def _make_cluster_config(nodes, client_addr, payload_size=2048, routing_size=16):
    """Build a minimal cluster config dict."""
    return {
        "params": {"payload_size": payload_size, "routing_size": routing_size, "max_hops": 5},
        "client": {"host": client_addr[0], "port": client_addr[1]},
        "nodes": nodes,
    }


def test_reach_register_then_forward_and_reply():
    """Full T1+T2: REACH registration → opaque forward → circuit reply."""
    params = OutfoxParams(payload_size=2048, routing_size=16, max_hops=5)

    # Keys
    supernode_pk, supernode_sk = params.kem.keygen()
    expert_pk, expert_sk = params.kem.keygen()

    # Sockets
    supernode_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    supernode_sock.bind(("127.0.0.1", 0))
    supernode_sock.settimeout(1.0)
    sn_addr = supernode_sock.getsockname()

    expert_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    expert_sock.bind(("127.0.0.1", 0))
    expert_sock.settimeout(1.0)
    ex_addr = expert_sock.getsockname()

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_sock.bind(("127.0.0.1", 0))
    client_sock.settimeout(1.0)
    cl_addr = client_sock.getsockname()

    # Build minimal cluster config for supernode runtime
    nodes = {
        "supernode": {
            "host": sn_addr[0], "port": sn_addr[1],
            "kem_pk": supernode_pk.hex(), "kem_sk": supernode_sk.hex(),
            "role": "any",
        },
        "expert_art": {
            "host": ex_addr[0], "port": ex_addr[1],
            "kem_pk": expert_pk.hex(), "kem_sk": expert_sk.hex(),
            "role": "expert",
        },
    }
    config_dict = _make_cluster_config(nodes, cl_addr)

    import tempfile, json as _json
    from pathlib import Path
    from por.config import ClusterConfig

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        _json.dump(config_dict, f)
        config_path = f.name

    cluster = ClusterConfig.load(config_path)
    runtime = WireNodeRuntime(cluster, "supernode", role="any")
    daemon = SupernodeDaemon(runtime, relay_secret=urandom(32))
    daemon.attach_socket(supernode_sock)

    # === T1: Expert registers via REACH ===
    reg_msg = encode_register("expert_art")
    expert_sock.sendto(reg_msg, sn_addr)

    # Supernode processes registration
    data, addr = supernode_sock.recvfrom(65535)
    daemon._handle_reach(data, addr)

    # Expert receives challenge
    # (In real flow, supernode sends challenge back. We simulate.)
    challenge = daemon.relay.request_registration(
        peer_id="expert_art",
        observed_endpoint=UdpEndpoint(*ex_addr),
    )

    # Expert confirms
    confirm_msg = encode_confirm("expert_art", challenge.cookie)
    expert_sock.sendto(confirm_msg, sn_addr)

    # Supernode processes confirm
    data, addr = supernode_sock.recvfrom(65535)
    daemon._handle_reach(data, addr)

    # Verify expert is registered
    assert daemon.forwarder.lookup_peer_addr("expert_art") is not None

    # Drain any REACH responses the expert received (challenge, etc.)
    while True:
        try:
            _drain, _ = expert_sock.recvfrom(65535)
        except socket.timeout:
            break

    # === T2: Client sends forward through supernode to expert ===
    forward_path = ["supernode", "expert_art"]
    route_infos, circuit_setup, client_peel_keys = build_native_forward_plan(tuple(forward_path))
    kem_keys = [supernode_pk, expert_pk]
    message = b'{"prompt": "test prompt"}'

    header, payload = packet_create(
        params, route_infos, kem_keys, message, circuit_setup=circuit_setup)

    # Client sends to supernode
    client_sock.sendto(encode_forward(header, payload), sn_addr)

    # Supernode processes forward (mix relay layer)
    data, sender = supernode_sock.recvfrom(65535)
    circuits = {}
    def on_circ(icid, ck, nh, ocid, ttl):
        circuits["inbound"] = icid.hex()
        circuits["key"] = ck.hex()
        circuits["outbound"] = ocid.hex()
        circuits["next_hop"] = nh.rstrip(b'\x00').decode('ascii', errors='replace')

    kind, body_a, body_b = decode_datagram(data, params.payload_size)
    assert kind == "forward"
    result = outfox_process(params, supernode_sk, supernode_pk,
                            (body_a, body_b), is_last=False, on_circuit=on_circ)
    assert result is not None
    _, _, (next_h, next_p) = result

    # Supernode forwards to expert via forwarder (tracks client addr for return)
    ok = daemon.forward_to_peer("expert_art", encode_forward(next_h, next_p), sender)
    assert ok

    # Expert receives and processes
    data, _ = expert_sock.recvfrom(65535)
    kind, body_a, body_b = decode_datagram(data, params.payload_size)
    assert kind == "forward"

    expert_circuits = {}
    def on_circ_ex(icid, ck, nh, ocid, ttl):
        expert_circuits["key"] = ck.hex()
        expert_circuits["outbound"] = ocid.hex()

    result = outfox_process(params, expert_sk, expert_pk,
                            (body_a, body_b), is_last=True, on_circuit=on_circ_ex)
    assert result is not None
    _, _, msg, _ = result
    assert b"test prompt" in msg

    # Expert streams reply back through supernode
    exit_key = bytes.fromhex(expert_circuits["key"])
    exit_outbound = bytes.fromhex(expert_circuits["outbound"])
    reply = json.dumps({"seq": 0, "data": "answer", "done": True}).encode()
    circuit_pkt = circuit_packet_create(params, exit_outbound, 1, reply, [exit_key])
    expert_sock.sendto(circuit_pkt, sn_addr)

    # Supernode receives circuit packet from expert
    data, expert_reply_addr = supernode_sock.recvfrom(65535)
    assert data[0:1] == CIRCUIT

    # Supernode processes circuit relay layer
    relay_key = bytes.fromhex(circuits["key"])
    outbound_cid = bytes.fromhex(circuits["outbound"])
    processed = circuit_packet_process(params, relay_key, data, outbound_link_cid=outbound_cid)
    assert processed is not None
    _, _, forwarded = processed

    # Supernode sends to client
    supernode_sock.sendto(forwarded, cl_addr)

    # Client receives and decrypts
    data, _ = client_sock.recvfrom(65535)
    plain = circuit_packet_decrypt(params, client_peel_keys, data)
    assert plain is not None
    chunk = json.loads(plain.decode("utf-8"))
    assert chunk["data"] == "answer"
    assert chunk["done"] is True

    # Cleanup
    supernode_sock.close()
    expert_sock.close()
    client_sock.close()

    import os
    os.unlink(config_path)

    print("[PASS] T1+T2: REACH register → opaque forward → circuit reply, no static expert IP.")


def test_unregistered_peer_dropped():
    """T5 security: unregistered peer packets are dropped."""
    params = OutfoxParams(payload_size=2048, routing_size=16, max_hops=5)
    pk, sk = params.kem.keygen()

    import tempfile, json as _json
    from por.config import ClusterConfig

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    addr = sock.getsockname()

    nodes = {"supernode": {
        "host": addr[0], "port": addr[1],
        "kem_pk": pk.hex(), "kem_sk": sk.hex(), "role": "any",
    }}
    config_dict = _make_cluster_config(nodes, ("127.0.0.1", 0))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        _json.dump(config_dict, f)
        config_path = f.name

    cluster = ClusterConfig.load(config_path)
    runtime = WireNodeRuntime(cluster, "supernode", role="any")
    daemon = SupernodeDaemon(runtime, relay_secret=urandom(32))

    # No registration — lookup should return None
    assert daemon.forwarder.lookup_peer_addr("unknown_peer") is None
    assert not daemon.forward_to_peer("unknown_peer", b"payload", ("127.0.0.1", 9999))

    sock.close()
    import os
    os.unlink(config_path)

    print("[PASS] T5: Unregistered peer dropped.")
