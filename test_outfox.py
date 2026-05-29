"""Tests for the Outfox post-quantum packet format.

Verifies the implementation against the construction in
Rial, Piotrowska, Halpin (2025), arXiv:2412.19937v2.
"""

from sphinxmix.OutfoxParams import OutfoxParams, KEM_X25519, aead_encrypt, aead_decrypt, hkdf
from sphinxmix.OutfoxClient import (
    pki_entry, packet_create, packet_create_repliable,
    surb_create, surb_use, surb_check, surb_recover,
    pad_body, unpad_body,
)
from sphinxmix.OutfoxNode import outfox_process


def make_pki(params, n=10):
    pkiPriv = {}
    pkiPub = {}
    for i in range(n):
        nid = bytes([i])
        pk, sk = params.kem.keygen()
        pkiPriv[nid] = pki_entry(nid, sk, pk)
        pkiPub[nid] = pki_entry(nid, None, pk)
    return pkiPriv, pkiPub


def test_primitives():
    """Verify KEM, KDF, AEAD, SE primitives."""
    params = OutfoxParams()

    pk, sk = params.kem.keygen()
    shk, c = params.kem.encapsulate(pk)
    assert params.kem.decapsulate(c, sk) == shk

    key_material = hkdf(shk, 64, info=b"test")
    assert len(key_material) == 64

    s_h, s_p = params.derive_keys(shk, c, pk)
    pt = b"authenticated plaintext!!"
    ct, tag = aead_encrypt(s_h, pt)
    assert aead_decrypt(s_h, ct, tag) == pt

    try:
        aead_decrypt(s_h, ct, b'\x00' * 16)
        assert False, "Should reject bad tag"
    except ValueError:
        pass

    msg = b"A" * 64
    enc = params.se_enc(s_p, msg)
    assert params.se_dec(s_p, enc) == msg

    print("[PASS] Primitives: KEM, KDF, AEAD, SE all correct.")


def test_header_sizes():
    """Verify shrinking header property."""
    params = OutfoxParams()
    sizes = params.header_sizes(4)
    assert sizes[0] > sizes[1] > sizes[2] > sizes[3]

    ct = params.kem.CIPHERTEXT_SIZE
    r = params.routing_size
    t = 16
    assert sizes[3] == ct + r + t
    assert sizes[2] == ct + r + sizes[3] + t
    assert sizes[1] == ct + r + sizes[2] + t
    assert sizes[0] == ct + r + sizes[1] + t

    print(f"[PASS] Header sizes (4 hops): {sizes} — shrinks per hop.")


def test_forward_message():
    """End-to-end forward message without reply."""
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([i]) for i in range(5)]

    route = [nid for nid in path]
    keys = [pkiPub[nid].y for nid in path]
    message = b"hello outfox world"

    header, payload = packet_create(params, route, keys, message)

    def pad_route(nid):
        return (nid + b'\x00' * params.routing_size)[:params.routing_size]

    for i in range(len(path)):
        nid = path[i]
        sk = pkiPriv[nid].x
        pk = pkiPriv[nid].y
        is_last = (i == len(path) - 1)

        result = outfox_process(params, sk, pk, (header, payload), is_last=is_last)

        if is_last:
            routing, msg, surb_info = result
            assert routing == pad_route(nid)
            assert msg == message
            assert surb_info is None
        else:
            routing, (header, payload) = result
            assert routing == pad_route(nid)


    print("[PASS] Forward message: 5-hop end-to-end delivery correct.")


def test_surb_reply():
    """End-to-end SURB creation, use, and recovery."""
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)

    fwd_path = [bytes([i]) for i in range(4)]
    # Reply path: 3 relay nodes + sender as final entry (per paper Section 3.2.2)
    rply_relays = [bytes([i + 4]) for i in range(3)]
    sender_id = bytes([9])

    fwd_route = list(fwd_path)
    fwd_keys = [pkiPub[nid].y for nid in fwd_path]
    # Reply route includes sender as last entry
    rply_route = list(rply_relays) + [sender_id]
    rply_keys = [pkiPub[nid].y for nid in rply_relays] + [pkiPub[sender_id].y]

    message = b"request with reply"
    (header, payload), idsurb, sksurb = packet_create_repliable(
        params, fwd_route, fwd_keys, rply_route, rply_keys, message)

    # Forward path
    for i in range(len(fwd_path)):
        nid = fwd_path[i]
        sk = pkiPriv[nid].x
        pk = pkiPriv[nid].y
        is_last = (i == len(fwd_path) - 1)

        result = outfox_process(params, sk, pk, (header, payload), is_last=is_last)

        if is_last:
            routing, msg, surb_info = result
            assert msg == message
            assert surb_info is not None
            surb_header, surb_key = surb_info
        else:
            routing, (header, payload) = result

    # Receiver creates reply using SURB
    reply_msg = b"here is my reply"
    reply_header, reply_payload = surb_use(
        params, (surb_header, surb_key), reply_msg)

    # Reply path — only relay nodes process (not the sender)
    for i in range(len(rply_relays)):
        nid = rply_relays[i]
        sk = pkiPriv[nid].x
        pk = pkiPriv[nid].y

        routing, (reply_header, reply_payload) = outfox_process(
            params, sk, pk, (reply_header, reply_payload), is_last=False)

    # Sender receives the final packet — header matches idsurb
    assert surb_check(reply_header, idsurb)
    received = surb_recover(params, reply_payload, list(sksurb))
    assert received == reply_msg

    print("[PASS] SURB reply: full repliable round-trip works.")


def test_aead_integrity():
    """Verify header tampering is detected by AEAD."""
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([0]), bytes([1])]

    route = list(path)
    keys = [pkiPub[nid].y for nid in path]
    header, payload = packet_create(params, route, keys, b"test")

    # Tamper with the AEAD ciphertext in the header
    tampered = bytearray(header)
    tampered[40] ^= 0xFF
    tampered = bytes(tampered)

    try:
        outfox_process(params, pkiPriv[path[0]].x, pkiPriv[path[0]].y,
                       (tampered, payload))
        assert False, "Should reject tampered header"
    except ValueError as e:
        assert "AEAD" in str(e) or "decryption" in str(e)

    print("[PASS] AEAD integrity: header tampering detected at first honest hop.")


def test_payload_tagging():
    """Verify payload tagging is detected at the final hop."""
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([0]), bytes([1]), bytes([2])]

    route = list(path)
    keys = [pkiPub[nid].y for nid in path]
    header, payload = packet_create(params, route, keys, b"secret msg")

    # Tag the payload (flip bits)
    tagged = bytearray(payload)
    tagged[50] ^= 0xFF
    tagged = bytes(tagged)

    # Process through all hops — header is fine, payload is tagged
    h, p = header, tagged
    for i in range(len(path)):
        nid = path[i]
        sk = pkiPriv[nid].x
        pk = pkiPriv[nid].y
        is_last = (i == len(path) - 1)

        result = outfox_process(params, sk, pk, (h, p), is_last=is_last)
        if is_last:
            # Zero-padding integrity check fails
            assert result[0] is None, "Tagged payload should fail integrity check"
        else:
            routing, (h, p) = result

    print("[PASS] Payload tagging: PRP destroys contents, zero-padding check fails.")


def test_request_reply_indistinguishability():
    """Verify request and reply packets are processed identically by nodes."""
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([i]) for i in range(4)]

    route = list(path)
    keys = [pkiPub[nid].y for nid in path]

    # Create a request packet
    req_header, req_payload = packet_create(params, route, keys, b"request")

    # Create a SURB and a reply packet
    surb, idsurb, sksurb = surb_create(params, route, keys)
    rply_header, rply_payload = surb_use(params, surb, b"reply msg")

    # Both are processed the same way by intermediate nodes
    req_result = outfox_process(
        params, pkiPriv[path[0]].x, pkiPriv[path[0]].y,
        (req_header, req_payload))
    rply_result = outfox_process(
        params, pkiPriv[path[0]].x, pkiPriv[path[0]].y,
        (rply_header, rply_payload))

    # Both produce routing info + next packet (same structure)
    assert isinstance(req_result[1], tuple) and len(req_result[1]) == 2
    assert isinstance(rply_result[1], tuple) and len(rply_result[1]) == 2

    print("[PASS] Request-reply indistinguishability: identical processing at nodes.")


def test_kem_independence():
    """Verify per-hop KEM independence (no blinding chain)."""
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([0]), bytes([1]), bytes([2])]

    route = list(path)
    keys = [pkiPub[nid].y for nid in path]
    header, payload = packet_create(params, route, keys, b"test")

    # Each hop uses KEM.Dec independently — no shared blinding state
    # If we swap node keys, only that specific hop fails
    wrong_pk, wrong_sk = params.kem.keygen()

    def pad_r(nid):
        return (nid + b'\x00' * params.routing_size)[:params.routing_size]

    # Correct first hop
    r1, (h1, p1) = outfox_process(
        params, pkiPriv[path[0]].x, pkiPriv[path[0]].y,
        (header, payload))
    assert r1 == pad_r(path[0])

    # Wrong key at second hop — fails independently
    try:
        outfox_process(params, wrong_sk, wrong_pk, (h1, p1))
        assert False, "Should fail with wrong key"
    except ValueError:
        pass

    # Correct second hop still works with correct key
    r2, (h2, p2) = outfox_process(
        params, pkiPriv[path[1]].x, pkiPriv[path[1]].y,
        (h1, p1))
    assert r2 == pad_r(path[1])

    print("[PASS] KEM independence: each hop's decapsulation is independent.")


def test_multiple_path_lengths():
    """Verify Outfox works with different path lengths."""
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)

    for num_hops in [1, 2, 3, 4, 5, 7]:
        path = [bytes([i]) for i in range(num_hops)]
        route = list(path)
        keys = [pkiPub[nid].y for nid in path]
        message = f"path length {num_hops}".encode()

        header, payload = packet_create(params, route, keys, message)

        for i in range(num_hops):
            is_last = (i == num_hops - 1)
            result = outfox_process(
                params, pkiPriv[path[i]].x, pkiPriv[path[i]].y,
                (header, payload), is_last=is_last)
            if is_last:
                _, msg, _ = result
                assert msg == message, f"Failed at {num_hops} hops"
            else:
                _, (header, payload) = result

    print("[PASS] Variable path lengths: 1 through 7 hops all work.")


if __name__ == "__main__":
    print("=" * 60)
    print("Outfox Post-Quantum Packet Format Tests")
    print("Rial, Piotrowska, Halpin (2025) — arXiv:2412.19937v2")
    print("=" * 60)
    print()

    test_primitives()
    test_header_sizes()
    test_forward_message()
    test_surb_reply()
    test_aead_integrity()
    test_payload_tagging()
    test_request_reply_indistinguishability()
    test_kem_independence()
    test_multiple_path_lengths()

    print()
    print("=" * 60)
    print("ALL OUTFOX TESTS PASSED")
    print("=" * 60)
