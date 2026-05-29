"""Outfox node-side packet processing.

Implements LMC.PacketProcess from Rial et al. (2025).

Each node:
  1. Extracts KEM ciphertext c_i from the header
  2. Decapsulates to get shared key shk_i
  3. Derives header key s_h and payload key s_p via HKDF
  4. AEAD-decrypts the header to get routing info + next header
  5. SE-decrypts the payload (length-preserving)
  6. Outputs (routing_info, next_packet) or (message, surb_info)
"""

from .OutfoxParams import aead_decrypt, AEAD_TAG_SIZE
from .OutfoxClient import unpad_body


def outfox_process(params, sk, pk, packet, is_last=False):
    """Process one layer of an Outfox packet.

    params: OutfoxParams
    sk: this node's KEM secret key
    pk: this node's KEM public key (needed for KDF context)
    packet: (header_bytes, payload_bytes)
    is_last: True if this is the final hop (receiver/exit gateway)

    Returns:
      If not last: (routing_info, (next_header, next_payload))
      If last:     (message, surb_info) where surb_info is
                   ((surb_header, surb_key), routing_info) or None
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

    next_payload = params.se_dec(s_p, payload)

    if is_last:
        routing_info = decrypted[:params.routing_size]

        if next_payload[:params.k] != b'\x00' * params.k:
            return None, None

        from struct import unpack as struct_unpack
        rest = next_payload[params.k:]
        surb_len = struct_unpack(">H", rest[:2])[0]
        surb_field = rest[2:2 + params.surb_size]
        msg_start = 2 + params.surb_size

        if surb_len == 0:
            msg = unpad_body(rest[msg_start:])
            return (routing_info, msg, None)

        surb_data = surb_field[:surb_len]
        surb_header = surb_data[:surb_len - params.k]
        surb_key = surb_data[surb_len - params.k:]
        msg = unpad_body(rest[msg_start:])
        return (routing_info, msg, (surb_header, surb_key))

    routing_info = decrypted[:params.routing_size]
    next_header = decrypted[params.routing_size:]

    return routing_info, (next_header, next_payload)


