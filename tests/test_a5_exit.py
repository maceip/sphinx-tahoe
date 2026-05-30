"""A5 exit test: Outfox native forward + circuit setup + stream return.

Proves the production path works end-to-end without demo modules:
  - packet_create with circuit_setup= (native, no POR1)
  - Relay installs circuit state via on_circuit callback
  - Exit decrypts PromptRequestEnvelope from forward payload
  - Exit streams response through circuit packets
  - Client peels all layers, verifies magic, recovers tokens

No MixnetSim, no udp_demo, no JSON frames — just OutfoxClient,
OutfoxNode, and OutfoxParams.
"""

from os import urandom

from sphinxmix.OutfoxParams import OutfoxParams, derive_circuit_key
from sphinxmix.OutfoxClient import packet_create, pad_body
from sphinxmix.OutfoxNode import (
    outfox_process, circuit_packet_create, circuit_packet_process,
    circuit_packet_decrypt, CircuitStream,
)
from por.envelope import PromptRequestEnvelope


def test_a5_native_forward_circuit_stream():
    """Full native path: forward installs circuits, exit streams back."""
    params = OutfoxParams(payload_size=4096, routing_size=16, max_hops=5)

    # 3 nodes: relay_a, relay_b, exit
    nodes = {}
    for name in ["relay_a", "relay_b", "exit"]:
        pk, sk = params.kem.keygen()
        nodes[name] = {"pk": pk, "sk": sk}

    forward_path = ["relay_a", "relay_b", "exit"]
    n = len(forward_path)

    # Client generates circuit setup (same as build_native_forward_plan)
    client_inbound = urandom(16)
    inbound_cids = [urandom(16) for _ in range(n)]
    outbound_cids = [client_inbound] + inbound_cids[:-1]
    seeds = [urandom(16) for _ in range(n)]
    keys = [derive_circuit_key(seeds[i], inbound_cids[i]) for i in range(n)]

    route = [forward_path[i + 1].encode() if i + 1 < n else b"" for i in range(n)]
    circuit_setup = []
    for i in range(n):
        return_next = "client" if i == 0 else forward_path[i - 1]
        circuit_setup.append({
            "inbound_link_cid": inbound_cids[i],
            "key_seed": seeds[i],
            "next_hop": return_next.encode(),
            "outbound_link_cid": outbound_cids[i],
            "ttl": 120,
        })

    # Build envelope
    envelope = PromptRequestEnvelope.visible_prompt(
        prompt="What is the capital of France?",
        selected_peer_id="exit",
        requested_expertise="geography",
    )

    kem_keys = [nodes[name]["pk"] for name in forward_path]
    header, payload = packet_create(
        params, route, kem_keys, envelope.to_json().encode(),
        circuit_setup=circuit_setup)

    # Process through relays
    installed_circuits = {}
    h, p = header, payload
    for i, name in enumerate(forward_path):
        circuits_for_hop = []
        def on_circ(icid, ck, nh, ocid, ttl, _out=circuits_for_hop):
            _out.append({
                "inbound": icid, "key": ck, "next_hop": nh,
                "outbound": ocid, "ttl": ttl,
            })

        is_last = (i == n - 1)
        if not is_last:
            result = outfox_process(params, nodes[name]["sk"], nodes[name]["pk"],
                                     (h, p), is_last=False, on_circuit=on_circ)
            assert result is not None, f"Forward failed at {name}"
            _, _, (h, p) = result
        else:
            result = outfox_process(params, nodes[name]["sk"], nodes[name]["pk"],
                                     (h, p), is_last=True, on_circuit=on_circ)
            assert result is not None, f"Exit processing failed"
            _, _, msg, _ = result
            delivered = PromptRequestEnvelope.from_json(msg)
            assert delivered.prompt_text() == "What is the capital of France?"

        assert len(circuits_for_hop) == 1, f"Expected 1 circuit at {name}, got {len(circuits_for_hop)}"
        c = circuits_for_hop[0]
        installed_circuits[name] = c

    # Exit creates circuit stream
    exit_circuit = installed_circuits["exit"]
    exit_outbound = exit_circuit["outbound"]
    exit_key = exit_circuit["key"]
    stream = CircuitStream(params, exit_outbound, [exit_key])

    # Stream tokens back
    tokens = [b"Paris", b" is", b" the", b" capital."]
    client_peel_keys = list(reversed(keys))

    for token in tokens:
        packet = stream.send(token)

        # Relay B processes (adds layer, rewrites CID)
        rb = installed_circuits["relay_b"]
        _, _, packet = circuit_packet_process(
            params, rb["key"], packet, outbound_link_cid=rb["outbound"])

        # Relay A processes
        ra = installed_circuits["relay_a"]
        _, _, packet = circuit_packet_process(
            params, ra["key"], packet, outbound_link_cid=ra["outbound"])

        # Client decrypts
        result = circuit_packet_decrypt(params, client_peel_keys, packet)
        assert result == token, f"Expected {token!r}, got {result!r}"

    # Verify non-adjacent unlinkability
    all_inbounds = {name: installed_circuits[name]["inbound"] for name in forward_path}
    assert len(set(v.hex() for v in all_inbounds.values())) == n

    print("[PASS] A5: Native Outfox forward + circuit stream + envelope, no demo modules.")


if __name__ == "__main__":
    test_a5_native_forward_circuit_stream()
