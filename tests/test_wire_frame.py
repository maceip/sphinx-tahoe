"""Unit tests for canonical binary wire framing (A2 prep)."""

from por.wire_frame import (
    CIRCUIT,
    FORWARD,
    SHUTDOWN,
    decode_datagram,
    encode_circuit,
    encode_forward,
    encode_shutdown,
)


def test_encode_forward_prefixes_type_byte():
    header = b"h" * 32
    payload = b"p" * 64
    raw = encode_forward(header, payload)
    assert raw[0:1] == FORWARD
    assert raw[1 : 1 + len(header)] == header
    assert raw[1 + len(header) :] == payload


def test_decode_forward_round_trip():
    header = b"h" * 48
    payload = b"p" * 2048
    raw = encode_forward(header, payload)
    kind, got_header, got_payload = decode_datagram(raw, payload_size=len(payload))
    assert kind == "forward"
    assert got_header == header
    assert got_payload == payload


def test_decode_circuit_round_trip():
    body = CIRCUIT + b"\x00" * 100
    raw = encode_circuit(body)
    kind, packet, extra = decode_datagram(raw, payload_size=2048)
    assert kind == "circuit"
    assert packet == raw
    assert extra is None


def test_shutdown_datagram():
    raw = encode_shutdown()
    kind, body, extra = decode_datagram(raw, payload_size=2048)
    assert kind == "shutdown"
    assert body == b""
    assert extra is None
    assert raw == SHUTDOWN
