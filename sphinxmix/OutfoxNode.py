"""Outfox node-side packet processing.

Implements LMC.PacketProcess from Rial et al. (2025).

Extended with P-OR additions:
  - Per-layer timestamp validation (replay rejection)
  - Dummy traffic flag parsing
  - Self-healing: fill random bytes for missing circuit messages

Each node:
  1. Extracts KEM ciphertext c_i from the header
  2. Decapsulates to get shared key shk_i
  3. Derives header key s_h and payload key s_p via HKDF
  4. AEAD-decrypts the header to get routing + timestamp + flag + next header
  5. Validates timestamp (rejects expired packets)
  6. SE-decrypts the payload (length-preserving)
  7. Outputs (routing_info, flag, (next_header, next_payload)) or final delivery
"""

import hmac as _hmac
from os import urandom

import struct as _struct

from collections import deque

from .OutfoxParams import (
    aead_decrypt, AEAD_TAG_SIZE, TIMESTAMP_SIZE, FLAG_SIZE,
    FLAG_REAL, FLAG_DUMMY, check_timestamp,
    CIRCUIT_MAGIC, CIRCUIT_TYPE, CIRCUIT_PACE_INTERVAL_MS, derive_circuit_key,
)
from .OutfoxClient import unpad_body


def outfox_process(params, sk, pk, packet, is_last=False, on_circuit=None):
    """Process one layer of an Outfox packet.

    Returns:
      If not last: (routing_info, flag, (next_header, next_payload))
      If last:     (routing_info, flag, msg, surb_info)
                   surb_info is ((surb_header, surb_key)) or None
      Returns None on expired timestamp or integrity failure.

    on_circuit: optional callback(circuit_id, circuit_key, next_hop, ttl)
      called when circuit setup fields are present in the routing metadata.
    """
    header, payload = packet
    ct_size = params.kem.CIPHERTEXT_SIZE

    c = header[:ct_size]
    encrypted_part = header[ct_size:]

    shk = params.kem.decapsulate(c, sk)
    if shk is None:
        return None

    s_h, s_p = params.derive_keys(shk, c, pk)

    beta = encrypted_part[:-AEAD_TAG_SIZE]
    gamma = encrypted_part[-AEAD_TAG_SIZE:]
    decrypted = aead_decrypt(s_h, beta, gamma)

    r = params.routing_size
    routing_info = decrypted[:r]
    ts = decrypted[r:r + TIMESTAMP_SIZE]
    flag = decrypted[r + TIMESTAMP_SIZE:r + TIMESTAMP_SIZE + FLAG_SIZE]
    rest = decrypted[r + TIMESTAMP_SIZE + FLAG_SIZE:]

    if flag[0] & 0x02 and on_circuit is not None:
        circuit_id = rest[:16]
        key_seed = rest[16:32]
        next_hop = rest[32:32 + r]
        ttl = _struct.unpack(">H", rest[32 + r:34 + r])[0]
        rest_header = rest[34 + r:]
        circuit_key = derive_circuit_key(key_seed, circuit_id)
        on_circuit(circuit_id, circuit_key, next_hop, ttl)
    elif flag[0] & 0x02:
        rest_header = rest[34 + r:]
    else:
        rest_header = rest

    if not check_timestamp(ts):
        return None

    next_payload = params.se_dec(s_p, payload)

    if is_last:
        if not _hmac.compare_digest(next_payload[:params.k], b'\x00' * params.k):
            return None

        from struct import unpack as struct_unpack
        inner = next_payload[params.k:]
        surb_len = struct_unpack(">H", inner[:2])[0]
        surb_field = inner[2:2 + params.surb_size]
        msg_start = 2 + params.surb_size

        if surb_len == 0:
            msg = unpad_body(inner[msg_start:])
            return (routing_info, flag, msg, None)

        surb_data = surb_field[:surb_len]
        surb_header = surb_data[:surb_len - params.k]
        surb_key = surb_data[surb_len - params.k:]
        msg = unpad_body(inner[msg_start:])
        return (routing_info, flag, msg, (surb_header, surb_key))

    return routing_info, flag, (rest_header, next_payload)


def circuit_process(params, circuit_key, payload):
    """Process a return-path circuit packet (symmetric-only).

    Used for streaming tokens back on established circuits.
    Just AES-CTR decrypt — no KEM, no AEAD header.
    """
    return params.aes_ctr(circuit_key, payload)


def circuit_self_heal(params, payload_size):
    """Generate random replacement for a missing circuit packet (Yodel self-healing)."""
    return urandom(payload_size)


def circuit_packet_create(params, circuit_id, nonce, token_data, circuit_keys):
    """Create a circuit return packet with multi-layer AES-CTR encryption.

    circuit_id:    16-byte circuit identifier
    nonce:         uint64 packet counter
    token_data:    plaintext token bytes
    circuit_keys:  list of keys, innermost first (exit key at index 0,
                   then relay keys in reverse reply-path order)

    Returns the complete packet (bytes), padded to params.payload_size.
    """
    nonce_bytes = _struct.pack(">Q", nonce)

    # encrypted region: inner_len(2) + magic(4) + token_data + padding
    encrypted_size = params.payload_size - 1 - 16 - 8  # minus type + cid + nonce
    inner = _struct.pack(">H", len(token_data)) + CIRCUIT_MAGIC + token_data
    pad_len = encrypted_size - len(inner)
    if pad_len < 0:
        raise ValueError("Token data too large for circuit packet")
    inner = inner + urandom(pad_len)

    ciphertext = inner
    for key in circuit_keys:
        iv = nonce_bytes + b'\x00' * 8
        ciphertext = params.aes_ctr(key, ciphertext, iv=iv)

    return CIRCUIT_TYPE + circuit_id + nonce_bytes + ciphertext


def circuit_packet_process(params, circuit_key, packet):
    """Process one layer of a circuit return packet at a relay.

    Verifies nonce monotonicity is the caller's responsibility (CircuitTable).
    Returns (circuit_id, nonce, decrypted_packet) where decrypted_packet has
    this relay's layer stripped but retains the wire format for forwarding.
    Returns None if packet is too short.
    """
    if len(packet) < 25:
        return None

    assert packet[0:1] == CIRCUIT_TYPE
    circuit_id = packet[1:17]
    nonce_bytes = packet[17:25]
    ciphertext = packet[25:]

    iv = nonce_bytes + b'\x00' * 8
    decrypted = params.aes_ctr(circuit_key, ciphertext, iv=iv)

    nonce = _struct.unpack(">Q", nonce_bytes)[0]
    forwarded = CIRCUIT_TYPE + circuit_id + nonce_bytes + decrypted
    return circuit_id, nonce, forwarded


def circuit_packet_decrypt(params, keys, packet):
    """Client-side decryption of a circuit packet.

    keys: single key (bytes) or list of keys to peel. When a list,
          all layers are peeled in order. The exit key (innermost)
          should be last in the list.
    Returns token_data bytes on success, None on corruption.
    """
    if len(packet) < 25:
        return None

    nonce_bytes = packet[17:25]
    ciphertext = packet[25:]
    iv = nonce_bytes + b'\x00' * 8

    if isinstance(keys, (list, tuple)):
        data = ciphertext
        for key in keys:
            data = params.aes_ctr(key, data, iv=iv)
        plaintext = data
    else:
        plaintext = params.aes_ctr(keys, ciphertext, iv=iv)

    if len(plaintext) < 6:
        return None

    inner_len = _struct.unpack(">H", plaintext[:2])[0]
    magic = plaintext[2:6]

    if magic != CIRCUIT_MAGIC:
        return None

    if 6 + inner_len > len(plaintext):
        return None

    return plaintext[6:6 + inner_len]


class CircuitStream:
    """Exit-side adapter that converts a token stream into circuit packets.

    Usage:
        stream = CircuitStream(params, circuit_id, circuit_keys)
        for chunk in sse_chunks:
            packet = stream.send(chunk)
            forward_to_relay(packet)
        # Send keepalive when idle:
        packet = stream.keepalive()
    """

    def __init__(self, params, circuit_id, circuit_keys):
        self.params = params
        self.circuit_id = circuit_id
        self.circuit_keys = circuit_keys
        self.nonce = 0
        self.max_token_size = params.payload_size - 1 - 16 - 8 - 6

    def send(self, token_data):
        """Encrypt a token into a circuit packet. Returns packet bytes."""
        if len(token_data) > self.max_token_size:
            raise ValueError(f"Token too large: {len(token_data)} > {self.max_token_size}")
        self.nonce += 1
        return circuit_packet_create(
            self.params, self.circuit_id, self.nonce,
            token_data, self.circuit_keys)

    def keepalive(self):
        """Send an empty keepalive packet (indistinguishable from a token packet)."""
        self.nonce += 1
        return circuit_packet_create(
            self.params, self.circuit_id, self.nonce,
            b'', self.circuit_keys)

    def send_chunked(self, data):
        """Split large data into multiple circuit packets. Returns list of packets."""
        packets = []
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + self.max_token_size]
            packets.append(self.send(chunk))
            offset += self.max_token_size
        if not packets:
            packets.append(self.send(b''))
        return packets


class PacedCircuitStream:
    """Constant-cadence wrapper around CircuitStream (TA mitigation v1).

    Token arrivals are queued; ``emit_due(now_ms)`` releases at most one
    circuit packet per ``interval_ms``. When the queue is empty but the
    session is still active, keepalives preserve a steady packet rhythm
    between irregular SSE chunks.

    This is the deliberate 20% solution for spec issue #4: it breaks the
    obvious "N tokens -> N immediate packets" burst signature at the exit.
    It is not GPA-resistant mixing and does not add relay-side cover traffic.
    """

    def __init__(self, stream, interval_ms=CIRCUIT_PACE_INTERVAL_MS):
        self.stream = stream
        self.interval_ms = max(1, int(interval_ms))
        self._queue = deque()
        self._active = False
        self._closed = False
        self._last_emit_ms = None

    @property
    def pending_count(self):
        return len(self._queue)

    def offer(self, token_data):
        """Queue a token for paced emission."""
        if self._closed:
            raise ValueError("paced circuit stream is closed")
        self._active = True
        self._queue.append(token_data)

    def close(self):
        """Stop keepalive padding; queued tokens may still be emitted."""
        self._closed = True

    def emit_due(self, now_ms):
        """Return packets ready at ``now_ms`` (0 or 1 packet)."""
        if not self._ready(now_ms):
            return []

        self._last_emit_ms = int(now_ms)
        if self._queue:
            return [self.stream.send(self._queue.popleft())]

        if self._active and not self._closed:
            return [self.stream.keepalive()]

        return []

    def _ready(self, now_ms):
        if self._last_emit_ms is None:
            return self._queue or (self._active and not self._closed)
        return (int(now_ms) - self._last_emit_ms) >= self.interval_ms
