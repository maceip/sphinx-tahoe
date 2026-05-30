"""P-OR mixnet simulator.

Wires together Outfox packets, return-path symmetric circuits,
cover traffic flags, and replay checks into a testable local model.

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
    FLAG_REAL, FLAG_DUMMY, CIRCUIT_TTL_SECONDS, CIRCUIT_PACE_INTERVAL_MS,
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
from .OutfoxNode import (
    outfox_process, circuit_process, circuit_self_heal,
    circuit_packet_create, circuit_packet_process, circuit_packet_decrypt,
    CircuitStream, PacedCircuitStream,
)


class CircuitCorrupted(Exception):
    """Raised when consecutive circuit packet corruption exceeds threshold."""
    def __init__(self, circuit_id):
        self.circuit_id = circuit_id
        super().__init__(f"Circuit {circuit_id!r} corrupted, re-establish required")


class PKI:
    """In-memory node directory with capability advertising.

    Each node registers its KEM public key, optional signing key,
    and its provider capabilities (which LLM providers/models it
    can reach via its API token).
    """

    def __init__(self):
        self.nodes = {}

    def register(self, node_id, kem_pk, sign_pk=None, providers=None):
        self.nodes[node_id] = {
            "kem_pk": kem_pk,
            "sign_pk": sign_pk,
            "providers": providers or [],
        }

    def get_kem_pk(self, node_id):
        return self.nodes[node_id]["kem_pk"]

    def get_sign_pk(self, node_id):
        return self.nodes[node_id].get("sign_pk")

    def get_providers(self, node_id):
        return self.nodes[node_id].get("providers", [])

    def all_node_ids(self):
        return list(self.nodes.keys())

    def find_exit_nodes(self, provider=None, model=None):
        """Find nodes that can serve as exit for a given provider/model.

        A node is a candidate exit if it advertises the requested provider.
        If model is specified, the node must also list that model.
        """
        results = []
        for node_id, info in self.nodes.items():
            for p in info.get("providers", []):
                if provider and p["name"] != provider:
                    continue
                if model and model not in p.get("models", []):
                    continue
                results.append(node_id)
                break
        return results

    def find_relays(self, exclude=None):
        """Find nodes suitable as guards/middles (any node not excluded)."""
        exclude = set(exclude or [])
        return [nid for nid in self.nodes if nid not in exclude]


class CircuitTable:
    """Per-node table of active return-path circuit keys.

    Keys are indexed by circuit_id (16 bytes).
    Entries store: symmetric key, next_hop, nonce high_watermark, timestamps.
    Bounded to max_entries with LRU eviction.
    """

    def __init__(self, ttl=CIRCUIT_TTL_SECONDS, max_entries=1024):
        self.ttl = ttl
        self.max_entries = max_entries
        self.entries = {}

    def store(self, circuit_id, symmetric_key, next_hop=None, ttl=None):
        if len(self.entries) >= self.max_entries and circuit_id not in self.entries:
            oldest_cid = min(self.entries, key=lambda c: self.entries[c]["last_active"])
            del self.entries[oldest_cid]
        self.entries[circuit_id] = {
            "key": symmetric_key,
            "next_hop": next_hop,
            "high_watermark": 0,
            "last_active": time.time(),
            "ttl": ttl if ttl is not None else self.ttl,
        }

    def lookup(self, circuit_id):
        entry = self.entries.get(circuit_id)
        if entry is None:
            return None
        entry_ttl = entry.get("ttl", self.ttl)
        if time.time() - entry["last_active"] > entry_ttl:
            del self.entries[circuit_id]
            return None
        entry["last_active"] = time.time()
        return entry

    def check_nonce(self, circuit_id, nonce):
        entry = self.entries.get(circuit_id)
        if entry is None:
            return False
        if nonce <= entry["high_watermark"]:
            return False
        entry["high_watermark"] = nonce
        return True

    def evict_expired(self):
        now = time.time()
        expired = [cid for cid, e in self.entries.items()
                   if now - e["last_active"] > e.get("ttl", self.ttl)]
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
    """A mix network node. Every node has full capability:
    forward routing, circuit processing, and (if configured) exit to LLM providers.

    A node becomes an exit node by registering providers with API tokens.
    """

    def __init__(self, node_id, params, kem_sk, kem_pk, providers=None):
        self.node_id = node_id
        self.params = params
        self.kem_sk = kem_sk
        self.kem_pk = kem_pk
        self.providers = providers or []
        self.circuits = CircuitTable()
        self.replay = ReplayTable()
        self.stats = {"forward": 0, "circuit": 0, "dummy_dropped": 0, "expired": 0}

    def process_packet(self, raw_bytes, is_last=False):
        """Dispatch a raw packet by type byte. Returns same as process_forward or process_circuit_packet."""
        if len(raw_bytes) < 1:
            return None
        if raw_bytes[0:1] == b'\x01':
            return self.process_circuit_packet(raw_bytes)
        if raw_bytes[0:1] == b'\x00':
            raw_bytes = raw_bytes[1:]
        header_size = len(raw_bytes) - self.params.payload_size
        if header_size <= 0:
            return None
        header = raw_bytes[:header_size]
        payload = raw_bytes[header_size:]
        return self.process_forward(header, payload, is_last=is_last)

    def process_forward(self, header, payload, is_last=False):
        """Process a forward-path Outfox packet.

        If circuit setup fields are present in the routing metadata,
        installs circuit state automatically.
        """
        def _install_circuit(circuit_id, circuit_key, next_hop, ttl):
            self.circuits.store(circuit_id, circuit_key, next_hop=next_hop, ttl=ttl)

        result = outfox_process(
            self.params, self.kem_sk, self.kem_pk,
            (header, payload), is_last=is_last,
            on_circuit=_install_circuit)

        if result is None:
            self.stats["expired"] += 1
            return None

        self.stats["forward"] += 1
        return result

    def process_circuit_packet(self, packet):
        """Process a circuit return packet. Returns (next_hop, forwarded_packet) or None."""
        if len(packet) < 25:
            return None
        circuit_id = packet[1:17]
        entry = self.circuits.lookup(circuit_id)
        if entry is None:
            return None

        import struct as _s
        nonce = _s.unpack(">Q", packet[17:25])[0]
        if not self.circuits.check_nonce(circuit_id, nonce):
            return None

        result = circuit_packet_process(self.params, entry["key"], packet)
        if result is None:
            return None

        _, _, forwarded = result
        self.stats["circuit"] += 1
        return entry["next_hop"], forwarded

    def register_circuit(self, circuit_id, symmetric_key, next_hop=None):
        self.circuits.store(circuit_id, symmetric_key, next_hop=next_hop)


class Client:
    """A mixnet client that sends prompts and receives responses."""

    def __init__(self, client_id, params, pki):
        self.client_id = client_id
        self.params = params
        self.pki = pki
        self.kem_pk, self.kem_sk = params.kem.keygen()
        self.sign_pk, self.sign_sk = generate_signing_keypair()
        self.pending_surbs = {}
        self.pending_circuits = {}

        pki.register(client_id, self.kem_pk, self.sign_pk)

    def select_path(self, provider=None, model=None, num_hops=3):
        """Select a forward path: random relays + a capable exit node."""
        import secrets
        exits = self.pki.find_exit_nodes(provider=provider, model=model)
        if not exits:
            raise ValueError(f"No exit node found for provider={provider} model={model}")
        exit_node = secrets.choice(exits)
        relays = self.pki.find_relays(exclude={exit_node, self.client_id})
        num_guards = min(num_hops - 1, len(relays))
        guards = []
        available = list(relays)
        for _ in range(num_guards):
            pick = secrets.choice(available)
            available.remove(pick)
            guards.append(pick)
        return guards + [exit_node]

    def create_forward(self, path, message):
        """Create a non-repliable forward packet."""
        route = [nid for nid in path]
        keys = [self.pki.get_kem_pk(nid) for nid in path]
        return packet_create(self.params, route, keys, message)

    def create_repliable(self, fwd_path, rply_path, message):
        """Create a repliable forward packet with embedded SURB.

        rply_path should be relay nodes only; self.client_id is appended automatically.
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

    def create_repliable_with_circuit(self, fwd_path, rply_path, message):
        """Create a repliable forward packet that also installs return circuits.

        Returns (header, payload, circuit_id). The forward path relays will
        install circuit state when processing the packet.
        """
        fwd_route = list(fwd_path)
        fwd_keys = [self.pki.get_kem_pk(nid) for nid in fwd_path]
        rply_route = list(rply_path) + [self.client_id]
        rply_keys = [self.pki.get_kem_pk(nid) for nid in rply_path] + [self.kem_pk]

        (header, payload), idsurb, sksurb, circuit_info = packet_create_repliable(
            self.params, fwd_route, fwd_keys, rply_route, rply_keys, message,
            install_circuit=True)

        self.pending_surbs[idsurb] = sksurb
        cid = circuit_info["circuit_id"]
        self.pending_circuits[cid] = {
            "keys": circuit_info["keys"],
            "nonce_watermark": 0,
            "corruption_count": 0,
        }
        return header, payload, cid

    MAX_CONSECUTIVE_CORRUPTION = 3

    def decrypt_circuit(self, packet):
        """Decrypt a circuit return packet. Returns token_data or None.

        Peels all layers: relay keys first (reverse of add order),
        then exit key (innermost).

        Raises CircuitCorrupted after MAX_CONSECUTIVE_CORRUPTION consecutive
        failures (magic mismatch), signaling the caller to re-establish.
        """
        if len(packet) < 25 or packet[0:1] != b'\x01':
            return None
        circuit_id = packet[1:17]
        entry = self.pending_circuits.get(circuit_id)
        if entry is None:
            return None

        import struct as _s
        nonce = _s.unpack(">Q", packet[17:25])[0]
        if nonce <= entry["nonce_watermark"]:
            return None
        entry["nonce_watermark"] = nonce

        peel_order = list(reversed(entry["keys"]))
        result = circuit_packet_decrypt(self.params, peel_order, packet)
        if result is None:
            entry["corruption_count"] += 1
            if entry["corruption_count"] >= self.MAX_CONSECUTIVE_CORRUPTION:
                del self.pending_circuits[circuit_id]
                raise CircuitCorrupted(circuit_id)
            return None
        entry["corruption_count"] = 0
        return result

    def receive_reply(self, header, payload):
        """Check if a packet is a reply to one of our SURBs and decrypt."""
        for idsurb, sksurb in self.pending_surbs.items():
            if surb_check(header, idsurb):
                msg = surb_recover(self.params, payload, list(sksurb))
                del self.pending_surbs[idsurb]
                return msg
        return None


class MixnetSim:
    """Local multi-node simulator. No network — direct function calls.

    Nodes are created with optional provider capabilities. A node that
    advertises providers can serve as an exit node for those providers.
    """

    def __init__(self, num_nodes=8, payload_size=1024, node_providers=None):
        """
        node_providers: optional dict mapping node index to list of provider dicts.
          e.g. {2: [{"name": "anthropic", "models": ["claude-sonnet-4-20250514"], "api_base": "http://..."}]}
          Nodes not in this dict are pure relays.
        """
        self.params = OutfoxParams(payload_size=payload_size)
        self.pki = PKI()
        self.nodes = {}
        node_providers = node_providers or {}

        for i in range(num_nodes):
            nid = struct.pack(">H", i)
            pk, sk = self.params.kem.keygen()
            providers = node_providers.get(i, [])
            node = MixNode(nid, self.params, sk, pk, providers=providers)
            self.nodes[nid] = node
            self.pki.register(nid, pk, providers=providers)

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

    def route_circuit_reply(self, fwd_path, circuit_id, exit_key, nonce, token_data):
        """Create a circuit packet at the exit and route it back through
        the forward path in reverse.

        The exit encrypts with exit_key only. Each intermediate relay
        adds its layer via AES-CTR. Returns the final packet for the client.
        """
        packet = circuit_packet_create(
            self.params, circuit_id, nonce, token_data, [exit_key])

        # Return path is reverse of forward, skipping the exit (it created the packet)
        relay_path = list(reversed(fwd_path[:-1]))
        for nid in relay_path:
            node = self.nodes[nid]
            result = node.process_circuit_packet(packet)
            if result is None:
                return None
            _, packet = result

        return packet

    def create_circuit_stream(self, fwd_path, circuit_id):
        """Create a CircuitStream at the exit node for sending return packets.

        Returns (stream, exit_key) where stream.send(token) produces packets
        and exit_key is for reference only.
        """
        exit_nid = fwd_path[-1]
        exit_node = self.nodes[exit_nid]
        entry = exit_node.circuits.lookup(circuit_id)
        if entry is None:
            return None, None
        stream = CircuitStream(self.params, circuit_id, [entry["key"]])
        return stream, entry["key"]

    def create_paced_circuit_stream(
        self, fwd_path, circuit_id, interval_ms=CIRCUIT_PACE_INTERVAL_MS
    ):
        """Create a PacedCircuitStream at the exit (constant cadence emitter)."""
        stream, exit_key = self.create_circuit_stream(fwd_path, circuit_id)
        if stream is None:
            return None, None
        return PacedCircuitStream(stream, interval_ms), exit_key

    def forward_circuit_packet(self, fwd_path, packet):
        """Route one circuit packet from exit through relays toward the client."""
        relay_path = list(reversed(fwd_path[:-1]))
        for nid in relay_path:
            node = self.nodes[nid]
            result = node.process_circuit_packet(packet)
            if result is None:
                return None
            _, packet = result
        return packet

    def stream_token(self, fwd_path, stream, token_data):
        """Stream a single token from exit through relays to client.

        Returns the circuit packet ready for client.decrypt_circuit().
        """
        packet = stream.send(token_data)
        return self.forward_circuit_packet(fwd_path, packet)

    def stream_paced_due(self, fwd_path, paced_stream, now_ms):
        """Emit and forward any circuit packets due at ``now_ms``."""
        packets = paced_stream.emit_due(now_ms)
        if not packets:
            return []
        routed = []
        for packet in packets:
            forwarded = self.forward_circuit_packet(fwd_path, packet)
            if forwarded is None:
                return routed
            routed.append(forwarded)
        return routed

    def stats(self):
        """Aggregate stats across all nodes."""
        totals = {"forward": 0, "circuit": 0, "dummy_dropped": 0, "expired": 0}
        for node in self.nodes.values():
            for k in totals:
                totals[k] += node.stats[k]
        return totals
