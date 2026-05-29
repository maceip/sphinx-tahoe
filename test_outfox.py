"""Tests for the Outfox post-quantum packet format with P-OR extensions.

Verifies: per-hop KEM, nested AEAD, HKDF, per-layer timestamps,
dummy flag, ML-DSA-65 signatures, return-path circuit processing,
and self-healing.
"""

from sphinxmix.OutfoxParams import (
    OutfoxParams, KEM_X25519,
    aead_encrypt, aead_decrypt, hkdf,
    make_timestamp, check_timestamp, sign_payload, verify_payload,
    generate_signing_keypair,
    FLAG_REAL, FLAG_DUMMY, CIRCUIT_TTL_SECONDS,
)
from sphinxmix.OutfoxClient import (
    pki_entry, packet_create, packet_create_repliable,
    packet_create_signed, packet_create_dummy,
    surb_create, surb_use, surb_check, surb_recover,
    pad_body, unpad_body,
)
from sphinxmix.OutfoxNode import outfox_process, circuit_process, circuit_self_heal
from os import urandom
import struct


def make_pki(params, n=10):
    pkiPriv = {}
    pkiPub = {}
    for i in range(n):
        nid = bytes([i])
        pk, sk = params.kem.keygen()
        pkiPriv[nid] = pki_entry(nid, sk, pk)
        pkiPub[nid] = pki_entry(nid, None, pk)
    return pkiPriv, pkiPub


def pad_route(nid, params):
    return (nid + b'\x00' * params.routing_size)[:params.routing_size]


def test_primitives():
    params = OutfoxParams()
    pk, sk = params.kem.keygen()
    shk, c = params.kem.encapsulate(pk)
    assert params.kem.decapsulate(c, sk) == shk

    s_h, s_p = params.derive_keys(shk, c, pk)
    pt = b"hello world!!!!!" * 4
    ct, tag = aead_encrypt(s_h, pt)
    assert aead_decrypt(s_h, ct, tag) == pt

    msg = urandom(128)
    assert params.se_dec(s_p, params.se_enc(s_p, msg)) == msg

    print("[PASS] Primitives: KEM, KDF, AEAD, SE.")


def test_timestamps():
    ts = make_timestamp()
    assert len(ts) == 8
    assert check_timestamp(ts, max_age_sec=5)

    old_ts = struct.pack(">Q", 0)
    assert not check_timestamp(old_ts, max_age_sec=5)

    print("[PASS] Timestamps: fresh accepted, expired rejected.")


def test_dilithium_signatures():
    pk, sk = generate_signing_keypair()
    msg = b"test payload content"
    sig = sign_payload(sk, msg)
    assert verify_payload(pk, msg, sig)
    assert not verify_payload(pk, b"tampered", sig)

    print("[PASS] ML-DSA-65 signatures: sign, verify, reject tampered.")


def test_forward_message():
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([i]) for i in range(5)]

    route = list(path)
    keys = [pkiPub[nid].y for nid in path]
    message = b"hello outfox world"
    header, payload = packet_create(params, route, keys, message)

    for i in range(len(path)):
        nid = path[i]
        is_last = (i == len(path) - 1)
        result = outfox_process(params, pkiPriv[nid].x, pkiPriv[nid].y,
                                (header, payload), is_last=is_last)
        assert result is not None, f"Processing failed at hop {i}"

        if is_last:
            routing, flag, msg, surb_info = result
            assert routing == pad_route(nid, params)
            assert flag == FLAG_REAL
            assert msg == message
            assert surb_info is None
        else:
            routing, flag, (header, payload) = result
            assert routing == pad_route(nid, params)
            assert flag == FLAG_REAL

    print("[PASS] Forward message: 5-hop delivery with timestamps and flags.")


def test_dummy_traffic():
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([0]), bytes([1])]

    route = list(path)
    keys = [pkiPub[nid].y for nid in path]

    header, payload = packet_create_dummy(params, route, keys)

    result = outfox_process(params, pkiPriv[path[0]].x, pkiPriv[path[0]].y,
                            (header, payload))
    assert result is not None
    routing, flag, (next_h, next_p) = result
    assert flag == FLAG_DUMMY

    print("[PASS] Dummy traffic: flag=DUMMY propagated through header.")


def test_signed_payload():
    params = OutfoxParams(payload_size=4096)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([0]), bytes([1])]

    sign_pk, sign_sk = generate_signing_keypair()
    sender_id = b"alice_id_1234567"
    receiver_id = b"bob_id_12345678"

    route = list(path)
    keys = [pkiPub[nid].y for nid in path]

    header, payload = packet_create_signed(
        params, route, keys, b"secret prompt",
        sign_sk, sender_id, receiver_id)

    for i in range(len(path)):
        is_last = (i == len(path) - 1)
        result = outfox_process(params, pkiPriv[path[i]].x, pkiPriv[path[i]].y,
                                (header, payload), is_last=is_last)
        if is_last:
            routing, flag, msg, _ = result
            sig_len = struct.unpack(">H", msg[:2])[0]
            signature = msg[2:2 + sig_len]
            signed_content = msg[2 + sig_len:]
            assert verify_payload(sign_pk, signed_content, signature)
            assert sender_id in signed_content
            assert receiver_id in signed_content
            assert b"secret prompt" in signed_content
        else:
            routing, flag, (header, payload) = result

    print("[PASS] Signed payload: ML-DSA-65 signature verified at exit.")


def test_surb_reply():
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)

    fwd_path = [bytes([i]) for i in range(4)]
    rply_relays = [bytes([i + 4]) for i in range(3)]
    sender_id = bytes([9])

    fwd_route = list(fwd_path)
    fwd_keys = [pkiPub[nid].y for nid in fwd_path]
    rply_route = list(rply_relays) + [sender_id]
    rply_keys = [pkiPub[nid].y for nid in rply_relays] + [pkiPub[sender_id].y]

    message = b"request with reply"
    (header, payload), idsurb, sksurb = packet_create_repliable(
        params, fwd_route, fwd_keys, rply_route, rply_keys, message)

    for i in range(len(fwd_path)):
        is_last = (i == len(fwd_path) - 1)
        result = outfox_process(params, pkiPriv[fwd_path[i]].x,
                                pkiPriv[fwd_path[i]].y,
                                (header, payload), is_last=is_last)
        if is_last:
            routing, flag, msg, surb_info = result
            assert msg == message
            assert surb_info is not None
            surb_header, surb_key = surb_info
        else:
            routing, flag, (header, payload) = result

    reply_msg = b"here is my reply"
    reply_header, reply_payload = surb_use(params, (surb_header, surb_key), reply_msg)

    for i in range(len(rply_relays)):
        nid = rply_relays[i]
        routing, flag, (reply_header, reply_payload) = outfox_process(
            params, pkiPriv[nid].x, pkiPriv[nid].y,
            (reply_header, reply_payload), is_last=False)

    assert surb_check(reply_header, idsurb)
    received = surb_recover(params, reply_payload, list(sksurb))
    assert received == reply_msg

    print("[PASS] SURB reply: full repliable round-trip with timestamps.")


def test_aead_integrity():
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([0]), bytes([1])]
    route = list(path)
    keys = [pkiPub[nid].y for nid in path]
    header, payload = packet_create(params, route, keys, b"test")

    tampered = bytearray(header)
    tampered[40] ^= 0xFF
    try:
        outfox_process(params, pkiPriv[path[0]].x, pkiPriv[path[0]].y,
                       (bytes(tampered), payload))
        assert False
    except ValueError:
        pass

    print("[PASS] AEAD integrity: header tampering detected.")


def test_payload_tagging():
    params = OutfoxParams(payload_size=1024)
    pkiPriv, pkiPub = make_pki(params)
    path = [bytes([0]), bytes([1]), bytes([2])]
    route = list(path)
    keys = [pkiPub[nid].y for nid in path]
    header, payload = packet_create(params, route, keys, b"secret msg")

    tagged = bytearray(payload)
    tagged[50] ^= 0xFF

    h, p = header, bytes(tagged)
    for i in range(len(path)):
        result = outfox_process(params, pkiPriv[path[i]].x, pkiPriv[path[i]].y,
                                (h, p), is_last=(i == len(path) - 1))
        if i == len(path) - 1:
            assert result is None
        else:
            _, _, (h, p) = result

    print("[PASS] Payload tagging: PRP destroys contents, detected at exit.")


def test_circuit_symmetric():
    """Test return-path symmetric circuit processing."""
    params = OutfoxParams(payload_size=1024)
    key = urandom(params.k)
    token_data = pad_body(params.payload_size, b"streaming token data here")

    encrypted = params.aes_ctr(key, token_data)
    decrypted = circuit_process(params, key, encrypted)
    assert decrypted == token_data

    healed = circuit_self_heal(params, params.payload_size)
    assert len(healed) == params.payload_size
    assert healed != token_data

    print("[PASS] Circuit symmetric: encrypt/decrypt + self-healing.")


def test_multiple_path_lengths():
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
            result = outfox_process(params, pkiPriv[path[i]].x,
                                    pkiPriv[path[i]].y,
                                    (header, payload), is_last=is_last)
            assert result is not None, f"Failed at {num_hops} hops, hop {i}"
            if is_last:
                _, _, msg, _ = result
                assert msg == message
            else:
                _, _, (header, payload) = result

    print("[PASS] Variable path lengths: 1 through 7 hops all work.")


if __name__ == "__main__":
    print("=" * 60)
    print("Outfox + P-OR Extensions Test Suite")
    print("=" * 60)
    print()

    test_primitives()
    test_timestamps()
    test_dilithium_signatures()
    test_forward_message()
    test_dummy_traffic()
    test_signed_payload()
    test_surb_reply()
    test_aead_integrity()
    test_payload_tagging()
    test_circuit_symmetric()
    test_multiple_path_lengths()

    print()
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
