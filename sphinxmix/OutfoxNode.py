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

from .OutfoxParams import (
    aead_decrypt, AEAD_TAG_SIZE, TIMESTAMP_SIZE, FLAG_SIZE,
    FLAG_REAL, FLAG_DUMMY, check_timestamp,
)
from .OutfoxClient import unpad_body


def outfox_process(params, sk, pk, packet, is_last=False):
    """Process one layer of an Outfox packet.

    Returns:
      If not last: (routing_info, flag, (next_header, next_payload))
      If last:     (routing_info, flag, msg, surb_info)
                   surb_info is ((surb_header, surb_key)) or None
      Returns None on expired timestamp or integrity failure.
    """
    header, payload = packet
    ct_size = params.kem.CIPHERTEXT_SIZE

    c = header[:ct_size]
    encrypted_part = header[ct_size:]

    shk = params.kem.decapsulate(c, sk)
    if shk is None:
        raise ValueError("KEM decapsulation failed")

    s_h, s_p = params.derive_keys(shk, c, pk)

    beta = encrypted_part[:-AEAD_TAG_SIZE]
    gamma = encrypted_part[-AEAD_TAG_SIZE:]
    decrypted = aead_decrypt(s_h, beta, gamma)

    r = params.routing_size
    routing_info = decrypted[:r]
    ts = decrypted[r:r + TIMESTAMP_SIZE]
    flag = decrypted[r + TIMESTAMP_SIZE:r + TIMESTAMP_SIZE + FLAG_SIZE]
    rest_header = decrypted[r + TIMESTAMP_SIZE + FLAG_SIZE:]

    if not check_timestamp(ts):
        return None

    next_payload = params.se_dec(s_p, payload)

    if is_last:
        if next_payload[:params.k] != b'\x00' * params.k:
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


try:
    from os import urandom
except ImportError:
    pass


