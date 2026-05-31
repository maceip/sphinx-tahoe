"""Expert advertisement and pool-commitment routing primitives.

The shape is intentionally close to mature provider-discovery systems:

* IPNI-style signed provider advertisements.
* Farcaster-style replicated/indexed event projection.
* Privacy-pool-style commitment roots and membership proofs.

The module is standalone and does not alter current daemon defaults. It gives the
protocol a concrete object model for "client commits to a pool; selected expert
proves pool membership" without requiring clients to download the global expert
manifest set.
"""

from __future__ import annotations

import argparse
import hmac
import json
import math
import random
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence


EXPERT_ADVERTISEMENT_VERSION = "tenet.expert_advertisement.v0"
EXPERT_POOL_VERSION = "tenet.expert_pool.v0"
EXPERT_POOL_MEMBER_PROOF_VERSION = "tenet.expert_pool_member_proof.v0"
DEFAULT_SELECTION_RULE = "hash_mod_pool_v0"


@dataclass(frozen=True)
class ExpertAdvertisement:
    """Public provider advertisement; private session config stays local."""

    version: str
    expert_peer_id: str
    manifest_digest: str
    topic_keys: tuple[str, ...]
    capability_keys: tuple[str, ...]
    reachability_ref: str
    quality_score: float
    availability_score: float
    issued_at: float
    expires_at: float
    sequence: int
    signature: str

    @classmethod
    def v0(
        cls,
        *,
        expert_peer_id: str,
        manifest_digest: str,
        topic_keys: Sequence[str],
        capability_keys: Sequence[str],
        reachability_ref: str,
        quality_score: float,
        availability_score: float,
        issued_at: float,
        expires_at: float,
        sequence: int,
        signer_key: str,
    ) -> "ExpertAdvertisement":
        unsigned = {
            "version": EXPERT_ADVERTISEMENT_VERSION,
            "expert_peer_id": expert_peer_id,
            "manifest_digest": manifest_digest,
            "topic_keys": tuple(topic_keys),
            "capability_keys": tuple(capability_keys),
            "reachability_ref": reachability_ref,
            "quality_score": quality_score,
            "availability_score": availability_score,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "sequence": sequence,
        }
        signature = _signature(unsigned, signer_key)
        return cls(signature=signature, **unsigned).validate()

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "ExpertAdvertisement":
        return cls(
            version=str(raw.get("version", "")),
            expert_peer_id=str(raw.get("expert_peer_id", "")),
            manifest_digest=str(raw.get("manifest_digest", "")),
            topic_keys=tuple(str(item) for item in _sequence_or_empty(raw.get("topic_keys"))),
            capability_keys=tuple(str(item) for item in _sequence_or_empty(raw.get("capability_keys"))),
            reachability_ref=str(raw.get("reachability_ref", "")),
            quality_score=float(raw.get("quality_score", 0.0)),
            availability_score=float(raw.get("availability_score", 0.0)),
            issued_at=float(raw.get("issued_at", 0.0)),
            expires_at=float(raw.get("expires_at", 0.0)),
            sequence=int(raw.get("sequence", 0)),
            signature=str(raw.get("signature", "")),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> "ExpertAdvertisement":
        if self.version != EXPERT_ADVERTISEMENT_VERSION:
            raise ValueError(f"unsupported expert advertisement version: {self.version!r}")
        if not self.expert_peer_id:
            raise ValueError("expert_peer_id is required")
        if not self.manifest_digest:
            raise ValueError("manifest_digest is required")
        if not self.topic_keys:
            raise ValueError("topic_keys must not be empty")
        if not self.capability_keys:
            raise ValueError("capability_keys must not be empty")
        if not self.reachability_ref:
            raise ValueError("reachability_ref is required")
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be between 0 and 1")
        if not 0.0 <= self.availability_score <= 1.0:
            raise ValueError("availability_score must be between 0 and 1")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if not self.signature:
            raise ValueError("signature is required")
        return self

    def verify_signature(self, signer_key: str) -> bool:
        unsigned = self.to_dict()
        unsigned.pop("signature", None)
        return hmac.compare_digest(self.signature, _signature(unsigned, signer_key))


@dataclass(frozen=True)
class ExpertPoolMember:
    peer_id: str
    manifest_digest: str
    reachability_ref: str
    quality_score: float
    availability_score: float
    weight: float

    @classmethod
    def from_ad(cls, ad: ExpertAdvertisement) -> "ExpertPoolMember":
        return cls(
            peer_id=ad.expert_peer_id,
            manifest_digest=ad.manifest_digest,
            reachability_ref=ad.reachability_ref,
            quality_score=ad.quality_score,
            availability_score=ad.availability_score,
            weight=_member_weight(ad),
        )

    def leaf_hash(self) -> str:
        return _hex_hash(b"tenet.pool.member.v0", _canonical_json(asdict(self)))


@dataclass(frozen=True)
class ExpertPoolCommitment:
    version: str
    pool_id: str
    topic_key: str
    policy_id: str
    candidate_count: int
    candidate_root: str
    min_pool_size: int
    selection_rule: str
    expires_at: float
    matcher_id: str
    matcher_nonce: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> "ExpertPoolCommitment":
        if self.version != EXPERT_POOL_VERSION:
            raise ValueError(f"unsupported pool version: {self.version!r}")
        if self.candidate_count <= 0:
            raise ValueError("candidate_count must be positive")
        if self.min_pool_size <= 0:
            raise ValueError("min_pool_size must be positive")
        if self.candidate_count < self.min_pool_size:
            raise ValueError("candidate_count below min_pool_size")
        if self.selection_rule != DEFAULT_SELECTION_RULE:
            raise ValueError(f"unsupported selection_rule: {self.selection_rule}")
        if not self.signature:
            raise ValueError("signature is required")
        return self

    def verify_signature(self, signer_key: str) -> bool:
        unsigned = self.to_dict()
        unsigned.pop("signature", None)
        return hmac.compare_digest(self.signature, _signature(unsigned, signer_key))


@dataclass(frozen=True)
class ExpertPoolMemberProof:
    version: str
    pool_id: str
    selected_index: int
    selected_member: ExpertPoolMember
    merkle_path: tuple[tuple[str, str], ...]
    candidate_root: str

    def verify(self, commitment: ExpertPoolCommitment) -> bool:
        if self.version != EXPERT_POOL_MEMBER_PROOF_VERSION:
            return False
        if self.pool_id != commitment.pool_id:
            return False
        if self.candidate_root != commitment.candidate_root:
            return False
        node = bytes.fromhex(self.selected_member.leaf_hash())
        index = self.selected_index
        for side, sibling_hex in self.merkle_path:
            sibling = bytes.fromhex(sibling_hex)
            if side == "left":
                node = _hash_pair(sibling, node)
            elif side == "right":
                node = _hash_pair(node, sibling)
            else:
                return False
            index //= 2
        return node.hex() == commitment.candidate_root


class ExpertMatcherIndex:
    """In-memory projection of expert advertisements into topic pools."""

    def __init__(self, *, matcher_id: str, signer_key: str):
        self.matcher_id = matcher_id
        self.signer_key = signer_key
        self._ads_by_peer: dict[str, ExpertAdvertisement] = {}
        self._topics: dict[str, set[str]] = defaultdict(set)

    def ingest(self, ad: ExpertAdvertisement, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if ad.expires_at <= now:
            return
        previous = self._ads_by_peer.get(ad.expert_peer_id)
        if previous is not None and previous.sequence > ad.sequence:
            return
        if previous is not None:
            for topic in previous.topic_keys:
                self._topics[topic].discard(previous.expert_peer_id)
        self._ads_by_peer[ad.expert_peer_id] = ad
        for topic in ad.topic_keys:
            self._topics[topic].add(ad.expert_peer_id)

    def build_pool(
        self,
        *,
        topic_key: str,
        request_id: str,
        client_nonce: str,
        min_pool_size: int = 8,
        max_pool_size: int = 20,
        policy_id: str = "balanced-v0",
        now: float | None = None,
        ttl_seconds: float = 30.0,
    ) -> tuple[ExpertPoolCommitment, tuple[ExpertPoolMember, ...], ExpertPoolMemberProof]:
        now = time.time() if now is None else now
        candidates = [
            self._ads_by_peer[peer_id]
            for peer_id in self._topics.get(topic_key, set())
            if self._ads_by_peer[peer_id].expires_at > now
        ]
        candidates.sort(key=lambda ad: (-_member_weight(ad), ad.expert_peer_id))
        selected_ads = tuple(candidates[:max_pool_size])
        if len(selected_ads) < min_pool_size:
            raise ValueError(f"not enough experts for topic_key={topic_key!r}")
        members = tuple(ExpertPoolMember.from_ad(ad) for ad in selected_ads)
        leaves = tuple(member.leaf_hash() for member in members)
        candidate_root = _merkle_root(leaves)
        matcher_nonce = _hex_hash(
            b"tenet.matcher.nonce.v0",
            self.matcher_id.encode("utf-8"),
            topic_key.encode("utf-8"),
            request_id.encode("utf-8"),
        )[:32]
        pool_id = _hex_hash(
            b"tenet.pool.id.v0",
            topic_key.encode("utf-8"),
            request_id.encode("utf-8"),
            candidate_root.encode("ascii"),
            matcher_nonce.encode("ascii"),
        )[:32]
        unsigned = {
            "version": EXPERT_POOL_VERSION,
            "pool_id": pool_id,
            "topic_key": topic_key,
            "policy_id": policy_id,
            "candidate_count": len(members),
            "candidate_root": candidate_root,
            "min_pool_size": min_pool_size,
            "selection_rule": DEFAULT_SELECTION_RULE,
            "expires_at": now + ttl_seconds,
            "matcher_id": self.matcher_id,
            "matcher_nonce": matcher_nonce,
        }
        commitment = ExpertPoolCommitment(
            signature=_signature(unsigned, self.signer_key),
            **unsigned,
        ).validate()
        selected_index = select_pool_index(
            commitment,
            request_id=request_id,
            client_nonce=client_nonce,
        )
        proof = ExpertPoolMemberProof(
            version=EXPERT_POOL_MEMBER_PROOF_VERSION,
            pool_id=pool_id,
            selected_index=selected_index,
            selected_member=members[selected_index],
            merkle_path=_merkle_proof(leaves, selected_index),
            candidate_root=candidate_root,
        )
        return commitment, members, proof


@dataclass(frozen=True)
class PoolSimulationResult:
    client_count: int
    expert_count: int
    topic_count: int
    success_count: int
    failure_count: int
    por_client_success_count: int
    p50_lookup_ms: float
    p95_lookup_ms: float
    average_pool_size: float
    max_expert_share: float
    topic_counts: dict[str, int]
    selected_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_expert_pool_routing(
    *,
    clients: int = 1000,
    experts: int = 500,
    topics: int = 32,
    min_pool_size: int = 8,
    max_pool_size: int = 20,
    seed: int = 7,
) -> PoolSimulationResult:
    rng = random.Random(seed)
    topic_keys = tuple(f"topic-{idx:02d}" for idx in range(topics))
    matcher = ExpertMatcherIndex(matcher_id="matcher-sim", signer_key="matcher-secret")
    now = 1_800_000_000.0
    for idx in range(experts):
        # Skew but keep coverage: every expert has one primary topic and one
        # secondary topic. Quality/availability are bounded nonzero.
        primary = topic_keys[idx % topics]
        secondary = topic_keys[(idx * 7 + 3) % topics]
        quality = 0.45 + (rng.random() * 0.55)
        availability = 0.55 + (rng.random() * 0.45)
        ad = ExpertAdvertisement.v0(
            expert_peer_id=f"expert-{idx:04d}",
            manifest_digest=_hex_hash(b"manifest", str(idx).encode("ascii")),
            topic_keys=(primary, secondary),
            capability_keys=("expert_session", "grounded_answer"),
            reachability_ref=f"relay://bootstrap/{idx:04d}",
            quality_score=quality,
            availability_score=availability,
            issued_at=now,
            expires_at=now + 600,
            sequence=idx,
            signer_key=f"expert-secret-{idx}",
        )
        matcher.ingest(ad, now=now)

    cluster = _simulation_cluster(experts)
    provider = PoolBackedDiscoveryProvider(
        matcher=matcher,
        min_pool_size=min_pool_size,
        max_pool_size=max_pool_size,
        now=now,
    )
    topic_counter: Counter[str] = Counter()
    selected_counter: Counter[str] = Counter()
    lookup_times: list[float] = []
    pool_sizes: list[int] = []
    failures = 0
    por_client_success = 0
    from . import client as client_mod

    original_send = client_mod.send_prepared_envelope

    def fake_send_prepared_envelope(**kwargs):
        envelope = kwargs["envelope"]
        return (
            f"[simulated expert response] peer={envelope.selected_peer_id}",
            ["client event=simulated_send_prepared_envelope"],
        )

    client_mod.send_prepared_envelope = fake_send_prepared_envelope
    try:
        _simulate_clients(
            clients=clients,
            topic_keys=topic_keys,
            rng=rng,
            now=now,
            cluster=cluster,
            provider=provider,
            topic_counter=topic_counter,
            selected_counter=selected_counter,
            lookup_times=lookup_times,
            pool_sizes=pool_sizes,
            failures_ref=[failures],
            por_client_success_ref=[por_client_success],
        )
        failures = provider.failure_count
        por_client_success = provider.client_success_count
    finally:
        client_mod.send_prepared_envelope = original_send

    success = clients - failures
    max_selected = max(selected_counter.values(), default=0)
    return PoolSimulationResult(
        client_count=clients,
        expert_count=experts,
        topic_count=topics,
        success_count=success,
        failure_count=failures,
        por_client_success_count=por_client_success,
        p50_lookup_ms=_percentile(lookup_times, 50),
        p95_lookup_ms=_percentile(lookup_times, 95),
        average_pool_size=(sum(pool_sizes) / len(pool_sizes)) if pool_sizes else 0.0,
        max_expert_share=(max_selected / success) if success else 0.0,
        topic_counts=dict(sorted(topic_counter.items())),
        selected_counts=dict(sorted(selected_counter.items())),
    )


def _simulate_clients(
    *,
    clients: int,
    topic_keys: Sequence[str],
    rng: random.Random,
    now: float,
    cluster,
    provider: "PoolBackedDiscoveryProvider",
    topic_counter: Counter[str],
    selected_counter: Counter[str],
    lookup_times: list[float],
    pool_sizes: list[int],
    failures_ref: list[int],
    por_client_success_ref: list[int],
) -> None:
    from .client import run_client_once
    from .expert_mode import ExpertModeConfig

    for idx in range(clients):
        topic = _sample_topic(topic_keys, rng)
        topic_counter[topic] += 1
        start = time.perf_counter()
        try:
            provider.next_request_context(
                request_id=f"request-{idx:04d}",
                client_nonce=f"client-nonce-{idx:04d}",
                now=now + idx * 0.001,
            )
            result = run_client_once(
                cluster=cluster,
                discovery_provider=provider,
                prompt=f"Need expert for {topic}",
                requested_expertise=topic,
                relay_path=("relay-sim",),
                expert_mode_config=ExpertModeConfig(min_pool_size=1),
                timeout=1.0,
            )
            if result.fallback_used or result.selected_peer_id is None:
                raise ValueError("por client fell back")
            por_client_success_ref[0] += 1
            provider.client_success_count += 1
            selected_counter[result.selected_peer_id] += 1
            pool_sizes.append(provider.last_pool_size)
        except ValueError:
            provider.failure_count += 1
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        # Add a tiny deterministic network/API component so simulator output is
        # closer to delegated routing behavior than pure CPU timing.
        lookup_times.append(elapsed_ms + 7.0 + rng.random() * 4.0)


class PoolBackedDiscoveryProvider:
    """Adapter that feeds pool-selected experts into the existing POR client."""

    def __init__(
        self,
        *,
        matcher: ExpertMatcherIndex,
        min_pool_size: int,
        max_pool_size: int,
        now: float,
    ):
        self.matcher = matcher
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.now = now
        self.request_id = "request-0"
        self.client_nonce = "client-nonce"
        self.last_commitment: ExpertPoolCommitment | None = None
        self.last_proof: ExpertPoolMemberProof | None = None
        self.last_pool_size = 0
        self.failure_count = 0
        self.client_success_count = 0

    def next_request_context(self, *, request_id: str, client_nonce: str, now: float) -> None:
        self.request_id = request_id
        self.client_nonce = client_nonce
        self.now = now

    def discover(self, request):
        from .directory import DiscoveryResult

        commitment, members, proof = self.matcher.build_pool(
            topic_key=request.intent.requested_expertise or request.intent.prompt,
            request_id=self.request_id,
            client_nonce=self.client_nonce,
            min_pool_size=self.min_pool_size,
            max_pool_size=self.max_pool_size,
            now=self.now,
        )
        if not proof.verify(commitment):
            raise AssertionError("pool proof did not verify")
        self.last_commitment = commitment
        self.last_proof = proof
        self.last_pool_size = len(members)
        return DiscoveryResult(
            candidates=(
                _peer_candidate_from_member(
                    proof.selected_member,
                    topic_key=request.intent.requested_expertise or request.intent.prompt,
                ),
            ),
            mode="pool_commitment_v0",
            snapshot_size=1,
            exact_query_sent=False,
            private_query_used=False,
            generated_at=str(self.now),
            note=f"pool_id={commitment.pool_id} candidate_count={commitment.candidate_count}",
        )

    def routing_kem_pk_hex(self, peer_id: str) -> str | None:
        # The simulation cluster contains all experts, so this is not needed for
        # dialability. The method exists to satisfy the same optional provider
        # interface used by real directory snapshots.
        return None


def select_pool_index(
    commitment: ExpertPoolCommitment,
    *,
    request_id: str,
    client_nonce: str,
) -> int:
    digest = _hex_hash(
        b"tenet.pool.select.v0",
        commitment.pool_id.encode("utf-8"),
        request_id.encode("utf-8"),
        client_nonce.encode("utf-8"),
        commitment.matcher_nonce.encode("utf-8"),
        commitment.candidate_root.encode("utf-8"),
    )
    return int(digest, 16) % commitment.candidate_count


def _peer_candidate_from_member(member: ExpertPoolMember, *, topic_key: str):
    from .expert_route import PeerCandidate, PeerObservation
    from .memory_index import MANIFEST_VERSION, MemoryManifest

    manifest = MemoryManifest(
        version=MANIFEST_VERSION,
        peer_id=member.peer_id,
        created_at="simulation",
        roots=tuple(),
        file_count=0,
        byte_count=0,
        chunk_count=1,
        token_count=1,
        file_types={},
        top_terms=tuple((term, 1) for term in _topic_terms(topic_key)),
        corpus_root=member.manifest_digest,
        index_digest=member.manifest_digest,
        privacy={
            "raw_text_published": False,
            "sources_in_manifest": False,
            "public_terms": True,
        },
    )
    return PeerCandidate(
        manifest=manifest,
        observation=PeerObservation(
            peer_id=member.peer_id,
            p50_latency_ms=100.0 / max(member.availability_score, 0.1),
            p95_latency_ms=200.0 / max(member.availability_score, 0.1),
            uptime=member.availability_score,
            completion_rate=member.quality_score,
        ),
    )


def _simulation_cluster(experts: int):
    from .config import ClusterConfig, ClusterNodeConfig, EndpointConfig, PacketConfig

    nodes = {
        "relay-sim": ClusterNodeConfig(
            node_id="relay-sim",
            host="127.0.0.1",
            port=9000,
            kem_pk_hex="01" * 32,
            kem_sk_hex="02" * 32,
            role="relay",
        )
    }
    for idx in range(experts):
        nodes[f"expert-{idx:04d}"] = ClusterNodeConfig(
            node_id=f"expert-{idx:04d}",
            host="127.0.0.1",
            port=10_000 + idx,
            kem_pk_hex=f"{(idx + 3) % 256:02x}" * 32,
            kem_sk_hex=f"{(idx + 4) % 256:02x}" * 32,
            role="expert",
        )
    return ClusterConfig(
        params=PacketConfig(payload_size=2048, routing_size=96, max_hops=5),
        client=EndpointConfig("127.0.0.1", 8999),
        nodes=nodes,
    )


def _topic_terms(topic_key: str) -> tuple[str, ...]:
    parts = [topic_key]
    parts.extend(topic_key.replace("-", " ").split())
    return tuple(dict.fromkeys(part for part in parts if len(part) >= 3))


def _sample_topic(topic_keys: Sequence[str], rng: random.Random) -> str:
    # Zipf-ish without external deps.
    weights = [1.0 / math.sqrt(idx + 1) for idx in range(len(topic_keys))]
    total = sum(weights)
    pick = rng.random() * total
    upto = 0.0
    for topic, weight in zip(topic_keys, weights):
        upto += weight
        if upto >= pick:
            return topic
    return topic_keys[-1]


def _member_weight(ad: ExpertAdvertisement) -> float:
    return (0.72 * ad.quality_score) + (0.28 * ad.availability_score)


def _signature(payload: Mapping[str, object], key: str) -> str:
    return hmac.new(
        key.encode("utf-8"),
        b"tenet.hmac.signature.v0" + _canonical_json(payload),
        sha256,
    ).hexdigest()


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hex_hash(*parts: bytes) -> str:
    h = sha256()
    for part in parts:
        h.update(len(part).to_bytes(8, "big"))
        h.update(part)
    return h.hexdigest()


def _hash_pair(left: bytes, right: bytes) -> bytes:
    return sha256(b"tenet.pool.node.v0" + left + right).digest()


def _merkle_root(leaves: Sequence[str]) -> str:
    if not leaves:
        return _hex_hash(b"tenet.pool.empty.v0")
    level = [bytes.fromhex(leaf) for leaf in leaves]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def _merkle_proof(leaves: Sequence[str], index: int) -> tuple[tuple[str, str], ...]:
    if index < 0 or index >= len(leaves):
        raise IndexError(index)
    level = [bytes.fromhex(leaf) for leaf in leaves]
    proof = []
    current = index
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        sibling_index = current ^ 1
        side = "left" if sibling_index < current else "right"
        proof.append((side, level[sibling_index].hex()))
        current //= 2
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return tuple(proof)


def _percentile(values: Sequence[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((percentile / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def _sequence_or_empty(value: object) -> Sequence[object]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("expected sequence")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulate expert pool routing.")
    parser.add_argument("--clients", type=int, default=1000)
    parser.add_argument("--experts", type=int, default=500)
    parser.add_argument("--topics", type=int, default=32)
    parser.add_argument("--min-pool-size", type=int, default=8)
    parser.add_argument("--max-pool-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = simulate_expert_pool_routing(
        clients=args.clients,
        experts=args.experts,
        topics=args.topics,
        min_pool_size=args.min_pool_size,
        max_pool_size=args.max_pool_size,
        seed=args.seed,
    )
    print(json.dumps(result.to_dict(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
