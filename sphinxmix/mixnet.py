"""P-OR Mixnet: multi-node simulator with QUIC transport.

Wires together Outfox packets, return-path symmetric circuits,
cover traffic, replay rejection, and aioquic transport into a
testable end-to-end mixnet.

Components:
  MixNode       — processes forward packets (Outfox) and circuit packets (AES)
  Client        — creates packets, manages circuits, decrypts replies
  PKI           — in-memory directory of node keys
  MixnetSim     — local multi-node simulator (no network, direct calls)
"""

import time
import struct
from os import urandom
from collections import namedtuple

from .OutfoxParams import (
    OutfoxParams, KEM_X25519,
    FLAG_REAL, FLAG_DUMMY, CIRCUIT_TTL_SECONDS,
    make_timestamp, check_timestamp,
    generate_signing_keypair, sign_payload, verify_payload,
    hkdf,
)
from .OutfoxClient import (
    packet_create, packet_create_repliable, packet_create_signed,
    packet_create_dummy,
    surb_create, surb_use, surb_check, surb_recover,
    pki_entry, pad_body, unpad_body,
)
from .OutfoxNode import outfox_process, circuit_process, circuit_self_heal


class PKI:
    """In-memory node directory. Maps node_id -> (pk_kem, pk_sign)."""

    def __init__(self):
        self.nodes = {}

    def register(self, node_id, kem_pk, sign_pk=None):
        self.nodes[node_id] = {"kem_pk": kem_pk, "sign_pk": sign_pk}

    def get_kem_pk(self, node_id):
        return self.nodes[node_id]["kem_pk"]

    def get_sign_pk(self, node_id):
        return self.nodes[node_id].get("sign_pk")

    def all_node_ids(self):
        return list(self.nodes.keys())


class CircuitTable:
    """Per-node table of active return-path circuit keys.

    Keys are indexed by circuit_id (16 bytes).
    TTL: 120 seconds idle, universal across all nodes.
    """

    def __init__(self, ttl=CIRCUIT_TTL_SECONDS):
        self.ttl = ttl
        self.entries = {}

    def store(self, circuit_id, symmetric_key):
        self.entries[circuit_id] = {
            "key": symmetric_key,
            "last_active": time.time(),
        }

    def lookup(self, circuit_id):
        entry = self.entries.get(circuit_id)
        if entry is None:
            return None
        if time.time() - entry["last_active"] > self.ttl:
            del self.entries[circuit_id]
            return None
        entry["last_active"] = time.time()
        return entry["key"]

    def evict_expired(self):
        now = time.time()
        expired = [cid for cid, e in self.entries.items()
                   if now - e["last_active"] > self.ttl]
        for cid in expired:
            del self.entries[cid]

    def size(self):
        return len(self.entries)


class ReplayTable:
    """Timestamp-based replay rejection. Zero-state: just check freshness."""

    def __init__(self, max_age=CIRCUIT_TTL_SECONDS):
        self.max_age = max_age

    def is_fresh(self, timestamp_bytes):
        return check_timestamp(timestamp_bytes, max_age_sec=self.max_age)


class MixNode:
    """A mix network node that processes forward and circuit packets."""

    def __init__(self, node_id, params, kem_sk, kem_pk):
        self.node_id = node_id
        self.params = params
        self.kem_sk = kem_sk
        self.kem_pk = kem_pk
        self.circuits = CircuitTable()
        self.replay = ReplayTable()
        self.stats = {"forward": 0, "circuit": 0, "dummy_dropped": 0, "expired": 0}

    def process_forward(self, header, payload, is_last=False):
        """Process a forward-path Outfox packet."""
        result = outfox_process(
            self.params, self.kem_sk, self.kem_pk,
            (header, payload), is_last=is_last)

        if result is None:
            self.stats["expired"] += 1
            return None

        self.stats["forward"] += 1
        return result

    def process_circuit(self, circuit_id, payload):
        """Process a return-path circuit packet (symmetric AES)."""
        key = self.circuits.lookup(circuit_id)
        if key is None:
            return circuit_self_heal(self.params, len(payload))

        self.stats["circuit"] += 1
        return circuit_process(self.params, key, payload)

    def register_circuit(self, circuit_id, symmetric_key):
        self.circuits.store(circuit_id, symmetric_key)


class Client:
    """A mixnet client that sends prompts and receives responses."""

    def __init__(self, client_id, params, pki):
        self.client_id = client_id
        self.params = params
        self.pki = pki
        self.kem_pk, self.kem_sk = params.kem.keygen()
        self.sign_pk, self.sign_sk = generate_signing_keypair()
        self.pending_surbs = {}

        pki.register(client_id, self.kem_pk, self.sign_pk)

    def create_forward(self, path, message):
        """Create a non-repliable forward packet."""
        route = [nid for nid in path]
        keys = [self.pki.get_kem_pk(nid) for nid in path]
        return packet_create(self.params, route, keys, message)

    def create_repliable(self, fwd_path, rply_path, message):
        """Create a repliable forward packet with embedded SURB.

        rply_path must include self.client_id as the last entry.
        """
        fwd_route = list(fwd_path)
        fwd_keys = [self.pki.get_kem_pk(nid) for nid in fwd_path]
        rply_route = list(rply_path) + [self.client_id]
        rply_keys = [self.pki.get_kem_pk(nid) for nid in rply_path] + [self.kem_pk]

        (header, payload), idsurb, sksurb = packet_create_repliable(
            self.params, fwd_route, fwd_keys, rply_route, rply_keys, message)

        self.pending_surbs[idsurb] = sksurb
        return header, payload

    def create_signed(self, path, receiver_id, message):
        """Create a forward packet with ML-DSA-65 signature."""
        route = [nid for nid in path]
        keys = [self.pki.get_kem_pk(nid) for nid in path]
        return packet_create_signed(
            self.params, route, keys, message,
            self.sign_sk, self.client_id, receiver_id)

    def create_dummy(self, path):
        """Create a cover traffic packet."""
        route = [nid for nid in path]
        keys = [self.pki.get_kem_pk(nid) for nid in path]
        return packet_create_dummy(self.params, route, keys)

    def receive_reply(self, header, payload):
        """Check if a packet is a reply to one of our SURBs and decrypt."""
        for idsurb, sksurb in self.pending_surbs.items():
            if surb_check(header, idsurb):
                msg = surb_recover(self.params, payload, list(sksurb))
                del self.pending_surbs[idsurb]
                return msg
        return None


class MixnetSim:
    """Local multi-node simulator. No network — direct function calls."""

    def __init__(self, num_nodes=8, payload_size=1024):
        self.params = OutfoxParams(payload_size=payload_size)
        self.pki = PKI()
        self.nodes = {}

        for i in range(num_nodes):
            nid = struct.pack(">H", i)
            pk, sk = self.params.kem.keygen()
            node = MixNode(nid, self.params, sk, pk)
            self.nodes[nid] = node
            self.pki.register(nid, pk)

    def node_ids(self):
        return list(self.nodes.keys())

    def create_client(self, client_id):
        return Client(client_id, self.params, self.pki)

    def route_forward(self, path, header, payload):
        """Route a forward packet through the given path of node IDs.

        Returns the final result from the exit node.
        """
        h, p = header, payload
        for i, nid in enumerate(path):
            node = self.nodes[nid]
            is_last = (i == len(path) - 1)
            result = node.process_forward(h, p, is_last=is_last)
            if result is None:
                return None
            if is_last:
                return result
            routing, flag, (h, p) = result
        return None

    def route_reply(self, rply_relay_path, header, payload):
        """Route a reply packet through relay nodes (not the final sender)."""
        h, p = header, payload
        for nid in rply_relay_path:
            node = self.nodes[nid]
            result = node.process_forward(h, p, is_last=False)
            if result is None:
                return None, None
            routing, flag, (h, p) = result
        return h, p

    def stats(self):
        """Aggregate stats across all nodes."""
        totals = {"forward": 0, "circuit": 0, "dummy_dropped": 0, "expired": 0}
        for node in self.nodes.values():
            for k in totals:
                totals[k] += node.stats[k]
        return totals
