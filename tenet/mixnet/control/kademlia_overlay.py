"""Real Kademlia DHT overlay for Tenet signed control records.

This replaces the previous in-memory "pseudo-DHT" (global xor sort over a
static peer list) with a library-backed Kademlia implementation that provides
the required mechanics for scale:

- routing table with k-buckets
- iterative node/value lookups (not a single sort of everything)
- peer discovery and liveness (periodic refresh / ping)
- churn handling and routing table maintenance
- replication factor (k) and provider storage for record keys
- refresh intervals and anti-entropy (internal to the server)
- bootstrap from known contacts with recovery
- bounded fanout (alpha concurrency, k-closest)

Application records (pools, experts, names, match results, trust updates, ...)
are still required to be signed, sequence-numbered, expiring, network-scoped,
and free of direct dial information. The DHT only carries the canonical
signed record bytes (or their JSON form); all validation, seq checks, and
expiry enforcement remain in the MixnetControlService / record validator.

The mixnet data plane is unchanged. This overlay is *only* for control-plane
discovery and replication of signed records. Client request traffic still
resolves via control records to a mixnet forward plan and never obtains raw
endpoints from here.

Kademlia traffic uses its own UDP port (main_port + 1 by default in the
integrating runtime) so it does not interfere with the mixnet wire format or
our custom TCTL control messages (which continue to be used for fast local
sync/gossip and as a secondary propagation path).
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Sequence

from kademlia.network import Server

from tenet.mixnet.control.records import (
    MAX_SIGNED_CONTROL_RECORD_BYTES,
    SignedControlRecord,
    signed_record_to_dht_bytes,
)

# publish() outcomes — publish never silently drops; it always returns one of
# these so the caller (and metrics) know what happened.
PUBLISH_SCHEDULED = "scheduled"
PUBLISH_QUEUED = "queued"
PUBLISH_REJECTED_OVERSIZED = "rejected_oversized"
PUBLISH_REJECTED_MAX_RECORDS = "rejected_max_records"
PUBLISH_REJECTED_MAX_PENDING = "rejected_max_pending"
PUBLISH_REJECTED_SERIALIZE = "rejected_serialize"


@dataclass
class DhtMetrics:
    """Counters for the control DHT overlay (best-effort observability)."""

    publishes_scheduled: int = 0
    publishes_queued: int = 0
    publishes_rejected: int = 0
    publish_set_ok: int = 0
    publish_set_failed: int = 0
    fetches: int = 0
    fetch_hits: int = 0
    fetch_misses: int = 0
    republish_cycles: int = 0
    republished_records: int = 0
    tasks_cancelled_on_stop: int = 0

    def snapshot(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class PeerFailureScore:
    """Tracks per-peer failures so flaky/dead contacts can be deprioritised."""

    _scores: dict[str, int] = field(default_factory=dict)

    def record_failure(self, peer: str) -> None:
        self._scores[peer] = self._scores.get(peer, 0) + 1

    def record_success(self, peer: str) -> None:
        self._scores[peer] = 0

    def score(self, peer: str) -> int:
        return self._scores.get(peer, 0)

    def is_suspect(self, peer: str, *, threshold: int = 3) -> bool:
        return self._scores.get(peer, 0) >= threshold

    def snapshot(self) -> dict[str, int]:
        return dict(self._scores)


class KademliaControlOverlay:
    """Background Kademlia node that stores and retrieves signed control records.

    Usage in a daemon:

        overlay = KademliaControlOverlay(node_id, listen_port=main_port + 1)
        overlay.start(bootstrap=[("10.0.0.5", 7001 + 1), ...])
        ...
        overlay.publish(record_key, signed_record)
        got = overlay.fetch(record_key)
        if got is not None:
            service.put_signed(got)   # re-validates

    The publish uses Kademlia set() which performs the iterative lookup for the
    k closest nodes for that key and replicates the value. fetch() performs an
    iterative get. Both survive the original bootstrap nodes disappearing as
    long as the k-bucket/routing information has enough live contacts and some
    replica holders for the key are reachable.
    """

    def __init__(
        self,
        local_node_label: str,
        *,
        listen_host: str = "0.0.0.0",
        listen_port: int,
        network_id: str | None = None,
        max_records: int = 4096,
        max_pending_publishes: int = 1024,
        republish_interval: float = 3600.0,
    ) -> None:
        self.local_node_label = str(local_node_label)
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.network_id = network_id  # used to scope DHT keys per network (fix eclipse)
        self.max_records = int(max_records)
        self.max_bytes = MAX_SIGNED_CONTROL_RECORD_BYTES
        self.max_pending_publishes = int(max_pending_publishes)
        self.republish_interval = float(republish_interval)
        self.server: Server | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._mesh_ready = threading.Event()  # set after listen + (optional) bootstrap; publishes wait for this to avoid "no neighbors" sets
        self._pending_lock = threading.Lock()
        self._pending_publishes: list[tuple[str, SignedControlRecord]] = []
        # Owned records: what this node is the publisher-of-record for. The
        # republish loop re-asserts these to the k-closest nodes so they survive
        # churn and storage expiry on replica holders.
        self._owned: dict[str, SignedControlRecord] = {}
        # In-flight set() futures (concurrent.futures.Future from
        # run_coroutine_threadsafe). Tracked so stop() can drain them and leave
        # NO pending asyncio task behind.
        self._inflight: set = set()
        self.metrics = DhtMetrics()
        self.peer_failures = PeerFailureScore()

    async def _serve(self, bootstrap: Sequence[tuple[str, int]]) -> None:
        # Each node gets its own storage (in-memory is fine; records are also
        # persisted by the control service's PersistentControlStore when the
        # node has the capability and a store_path).
        self.server = Server()
        await self.server.listen(self.listen_port, self.listen_host)
        self._ready.set()
        # NOTE: we intentionally do NOT flush publishes here. We wait until
        # after bootstrap (if any) so that the first server.set() calls see a
        # populated routing table instead of "no known neighbors".
        if bootstrap:
            # bootstrap() performs FIND_NODE against the given contacts and
            # populates the routing table. Real iterative behavior (and safe
            # replication on publish) starts here.
            await self.server.bootstrap(list(bootstrap))
        # Now we have (or had no need for) initial neighbors. Safe to publish
        # with expectation of replication to k-closest.
        self._mesh_ready.set()
        # Startup republish: re-assert any persisted/owned records now that the
        # mesh is ready (callers populate _owned before/just after start(), and
        # owned records survive a stop()/start() cycle on the same object).
        self._flush_pending()
        with self._pending_lock:
            owned = list(self._owned.items())
        for rec_key, srec in owned:
            self.publish(rec_key, srec)
        republisher = asyncio.ensure_future(self._republish_loop())
        try:
            # Idle until asked to stop. The Server's internal refresh loops keep
            # buckets and replicas alive.
            while not self._stop.is_set():
                await asyncio.sleep(0.25)
        finally:
            # Clean shutdown: cancel the republish loop and DRAIN every in-flight
            # task so the loop never closes with pending work. This is what makes
            # stop() leave no pending asyncio tasks.
            republisher.cancel()
            pending = [
                task
                for task in asyncio.all_tasks(self._loop)
                if task is not asyncio.current_task()
            ]
            for task in pending:
                task.cancel()
            self.metrics.tasks_cancelled_on_stop += len(pending)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _republish_loop(self) -> None:
        """Periodically re-assert owned records to the k-closest nodes."""
        try:
            while not self._stop.is_set():
                await asyncio.sleep(self.republish_interval)
                if self._stop.is_set():
                    break
                self.metrics.republish_cycles += 1
                with self._pending_lock:
                    owned = list(self._owned.items())
                for rec_key, srec in owned:
                    self.publish(rec_key, srec)
                    self.metrics.republished_records += 1
        except asyncio.CancelledError:
            return

    def start(self, bootstrap: Sequence[tuple[str, int]] = ()) -> None:
        """Launch the Kademlia server in a daemon thread with its own event loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def _runner() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._serve(bootstrap))
            finally:
                try:
                    if self.server is not None:
                        self.server.stop()
                except Exception:
                    pass
                try:
                    self._mesh_ready.clear()
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(
            target=_runner,
            name=f"tenet-kad-{self.local_node_label}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal shutdown and wait for the thread, leaving no pending tasks.

        The serving coroutine's ``finally`` cancels the republish loop and drains
        every in-flight task before the loop closes, so a stopped overlay never
        emits "Task was destroyed but it is pending" warnings.
        """
        self._stop.set()
        if self._loop is not None:
            # Wake the sleep loop.
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        # Any futures still tracked here are already cancelled by the drain; clear
        # references so a stopped overlay holds nothing.
        for fut in list(self._inflight):
            fut.cancel()
        self._inflight.clear()
        self._ready.clear()
        self._mesh_ready.clear()

    def owned_record_count(self) -> int:
        with self._pending_lock:
            return len(self._owned)

    def pending_publish_count(self) -> int:
        with self._pending_lock:
            return len(self._pending_publishes)

    def wait_for_mesh(self, timeout: float = 5.0) -> bool:
        """Block (with timeout) until this overlay has completed listen and its
        initial bootstrap (if bootstrap contacts were supplied to start()).

        Returns True if the mesh became ready within the timeout. Callers that
        want their publishes to have a good chance of replicating on first try
        (instead of being queued until the internal bootstrap settles) should
        call this after start() and before the first wave of publish() calls.
        """
        return self._mesh_ready.wait(timeout=timeout)

    def _derive_dht_key(self, record_key: str) -> str:
        """Return the network-scoped storage key for Kademlia.

        This prevents one network from occupying slots that belong to another
        (e.g. pool/foo from netA must not shadow pool/foo for netB).
        """
        if not self.network_id:
            return record_key
        return sha256(
            b"tenet-control-dht-v1\x00"
            + self.network_id.encode("utf-8")
            + b"\x00"
            + record_key.encode("utf-8")
        ).hexdigest()

    def _flush_pending(self) -> None:
        with self._pending_lock:
            if not self._pending_publishes:
                return
            pend = self._pending_publishes
            self._pending_publishes = []
        for rec_key, srec in pend:
            try:
                self.publish(rec_key, srec)
            except Exception:
                pass

    def publish(self, key: str, signed: SignedControlRecord) -> str:
        """Publish a signed record. Returns a PUBLISH_* status.

        The value stored in Kademlia is the canonical to_dict() form under a
        network-scoped key. publish never silently drops: it either confirms it
        scheduled the set, confirms it queued (mesh not ready), or returns a
        rejection status (oversized / over a capacity bound). Callers must still
        validate on retrieval.
        """
        # Size bound (fix 7): reject oversized before we ever call into Kademlia set.
        try:
            blob = signed_record_to_dht_bytes(signed)
        except Exception:
            self.metrics.publishes_rejected += 1
            return PUBLISH_REJECTED_SERIALIZE
        if len(blob) > self.max_bytes:
            self.metrics.publishes_rejected += 1
            return PUBLISH_REJECTED_OVERSIZED

        # Capacity bound on owned records (a new key beyond the cap is refused;
        # updating an existing owned key is always allowed).
        with self._pending_lock:
            is_new_key = key not in self._owned
            if is_new_key and len(self._owned) >= self.max_records:
                self.metrics.publishes_rejected += 1
                return PUBLISH_REJECTED_MAX_RECORDS
            self._owned[key] = signed

        if self.server is None or self._loop is None or not self._mesh_ready.is_set():
            # Queue while the mesh is not ready (post-bootstrap). Bounded so a
            # stuck bootstrap cannot grow the queue without limit.
            if self._thread and self._thread.is_alive():
                with self._pending_lock:
                    if len(self._pending_publishes) >= self.max_pending_publishes:
                        self.metrics.publishes_rejected += 1
                        return PUBLISH_REJECTED_MAX_PENDING
                    self._pending_publishes.append((key, signed))
                self.metrics.publishes_queued += 1
                return PUBLISH_QUEUED
            self.metrics.publishes_rejected += 1
            return PUBLISH_REJECTED_MAX_PENDING

        self._flush_pending()

        dht_key = self._derive_dht_key(key)  # network-scoped to prevent cross-net eclipse (fix 1)

        async def _do_set() -> None:
            if self.server is None:
                return
            try:
                await self.server.set(dht_key, blob.decode("utf-8"))
                self.metrics.publish_set_ok += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self.metrics.publish_set_failed += 1

        try:
            fut = asyncio.run_coroutine_threadsafe(_do_set(), self._loop)
        except Exception:
            self.metrics.publishes_rejected += 1
            return PUBLISH_REJECTED_MAX_PENDING
        # Track the future so stop()/flush() can drain it cleanly.
        self._inflight.add(fut)
        fut.add_done_callback(lambda f: self._inflight.discard(f))
        self.metrics.publishes_scheduled += 1
        return PUBLISH_SCHEDULED

    def flush(self, timeout: float = 5.0) -> bool:
        """Flush queued publishes and wait for in-flight sets to settle.

        Returns True if everything in flight completed within the timeout.
        """
        self._flush_pending()
        inflight = list(self._inflight)
        if not inflight:
            return True
        deadline_each = max(0.0, timeout) / max(1, len(inflight))
        ok = True
        for fut in inflight:
            try:
                fut.result(timeout=deadline_each if deadline_each > 0 else None)
            except Exception:
                ok = False
        return ok

    def fetch(self, key: str, timeout: float = 4.0) -> SignedControlRecord | None:
        """Perform an iterative Kademlia GET for the key and return a parsed
        SignedControlRecord (or None on miss/timeout/error).

        The returned object has *not* been signature-validated against any
        particular roots; the caller (usually MixnetControlService) must call
        .validate(...) with its verify_keys before trusting/ingesting it.
        Size is checked after retrieval to avoid accepting huge blobs from the DHT.
        """
        if self.server is None or self._loop is None:
            return None

        dht_key = self._derive_dht_key(key)

        async def _do_get() -> str | None:
            if self.server is None:
                return None
            return await self.server.get(dht_key)

        self.metrics.fetches += 1
        try:
            fut = asyncio.run_coroutine_threadsafe(_do_get(), self._loop)
            raw = fut.result(timeout=timeout)
        except Exception:
            self.metrics.fetch_misses += 1
            return None
        if not raw:
            self.metrics.fetch_misses += 1
            return None
        try:
            data = raw if isinstance(raw, (bytes, bytearray)) else raw.encode("utf-8")
            if len(data) > MAX_SIGNED_CONTROL_RECORD_BYTES:
                self.metrics.fetch_misses += 1
                return None  # oversized from DHT; reject (fix 7)
            record = SignedControlRecord.from_dict(json.loads(data))
            self.metrics.fetch_hits += 1
            return record
        except Exception:
            self.metrics.fetch_misses += 1
            return None

    def control_wire_contacts(
        self,
        *,
        limit: int = 20,
        timeout: float = 1.0,
    ) -> tuple[tuple[str, tuple[str, int]], ...]:
        """Return live peers learned by Kademlia as control-wire contacts.

        Signed control records still do not contain host/port material. This
        method reads the library routing table at runtime and derives the Tenet
        control-wire port from the local convention that Kademlia listens on
        ``control_port + 1``. The peer id returned here is the Kademlia node id
        hex, suitable for logging/deduping but not as route truth.
        """

        if self.server is None or self._loop is None or not self._mesh_ready.is_set():
            return tuple()

        async def _do_contacts() -> tuple[tuple[str, tuple[str, int]], ...]:
            server = self.server
            if server is None:
                return tuple()
            protocol = getattr(server, "protocol", None)
            router = getattr(protocol, "router", None)
            buckets = tuple(getattr(router, "buckets", ()) or ())
            contacts: list[tuple[str, tuple[str, int]]] = []
            local = getattr(server, "node", None)
            seen: set[tuple[str, int]] = set()
            for bucket in buckets:
                get_nodes = getattr(bucket, "get_nodes", None)
                if not callable(get_nodes):
                    continue
                for node in get_nodes():
                    host = str(getattr(node, "ip", "") or "")
                    dht_port = int(getattr(node, "port", 0) or 0)
                    if not host or dht_port <= 1:
                        continue
                    if local is not None and node.same_home_as(local):
                        continue
                    control_port = dht_port - 1
                    addr = (host, control_port)
                    if addr in seen:
                        continue
                    seen.add(addr)
                    node_id = getattr(node, "id", b"")
                    if isinstance(node_id, (bytes, bytearray)):
                        label = node_id.hex()
                    else:
                        label = str(getattr(node, "long_id", node_id))
                    contacts.append((f"kad:{label}", addr))
            contacts.sort(key=lambda item: (item[1][0], item[1][1], item[0]))
            return tuple(contacts[: max(0, int(limit))])

        try:
            fut = asyncio.run_coroutine_threadsafe(_do_contacts(), self._loop)
            return fut.result(timeout=timeout)
        except Exception:
            return tuple()

    @property
    def is_running(self) -> bool:
        return bool(self.server is not None and self._thread and self._thread.is_alive())

    @property
    def is_mesh_ready(self) -> bool:
        """True once listen has completed and any initial bootstrap supplied to
        start() has finished (routing table has had a chance to learn neighbors).
        publish() will only perform replicating Kademlia sets after this is true.
        """
        return self._mesh_ready.is_set()
