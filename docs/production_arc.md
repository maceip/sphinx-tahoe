# P-OR Production Arc

**This file is the coordination doc.** All parallel teams check here for
constraints, ownership, and status. New updates go in
**[Coordination log](#coordination-log)** at the bottom.

Status: coordination note for current Python work. This is not a privacy claim
or release checklist.

**Last updated:** 2026-05-30 (persistent client + product SSE landed)

---

## Product stance — one binary, optional supernode

**Target:** one **`por` client binary** that everyone runs. No separate
“gateway” binary, no optional alternate entrypoints for end users.

| Everyone runs | Same binary, default mode: send prompts through the mixnet |
|---------------|-----------------------------------------------------------|
| **Supernode** | Same binary, **promoted by config + capability** (e.g. you have a **public IP**): may relay for others, register in directory, accept inbound mix work |
| **Not allowed** | A second user-facing binary for “HTTP edge”, “gateway”, or “provider front door” |

HTTP/SSE (browser or provider streaming) is a **local interface on the same
client process** — e.g. listen on localhost, translate HTTP/SSE ↔
`run_client_once()` / persistent client session. It is **not** a different node
type and not a mix hop.

**Mix roles today (interim):** harnesses spawn **`por relay`** / **`por expert`**
subcommands of the same binary. Legacy console names (`por-relay`, etc.) print a
deprecation notice and delegate here.

---

## Convergence checklist (one binary — must complete)

Track in coordination log when items flip to done.

| Step | Status | Owner |
|------|--------|-------|
| Primary console script **`por`** with subcommands | **Done** — `por send\|relay\|expert\|directory\|run` | A1 |
| `python -m por` same as `por` CLI | **Done** — `por/__main__.py` | A1 |
| UDP demo spawns `python -m por relay\|expert` | **Done** — `udp_demo._start_nodes` | A1 |
| Legacy `por-relay` / `por-expert` / `por-client` delegate + deprecate | **Done** — stderr notice | A1 |
| **`por run --config`** from single `por.config.v1` for relay/expert/client | **Done** — config carries KEM identity + client options | A1 + runtime |
| Persistent client loop (`por run`, role=client) | **Done (MVP)** — local process session reused across HTTP requests | A1 |
| Supernode promotion flags in one config file | **Done (schema)** — public IP + relay registration flags | A1 + D |
| Local HTTP/SSE on client process (not separate binary) | **Done** — same `por run` client process, chunk SSE | C |
| Remove legacy console script names | **Open** — after one release cycle | A1 |

**Gate:** do not add new top-level console scripts. New behavior → **`por` subcommand** or config flag on the same binary.

### Runtime agent gate

Binary framing is now present in `WireNodeRuntime` + `por/client.py`. Runtime
work may proceed, but do not change recv/send framing in client/runtime without a
wire-owner review.

Runtime may work on peer-address transport IO and future pacing. Do not change
recv/send framing in client/runtime without a wire-owner review.

**Freehold NAT synthesis** in `docs/por_transport_backlog.md` remains useful
context. Implementation must stay relay-first and must not parse app payloads.

---

## Parked — Freehold NAT synthesis (do not drop)

**Priority:** wire A2 + process-wire A5 **done**; **next** is transport IO
(supernode inline forward + client dials supernode endpoint). Not current sprint
for full Milestone D, but **must stay assigned** (end-user “run at home” bar).

**Source repo:** [maceip/freehold](https://github.com/maceip/freehold) (reviewed
2026-05-30; see commit list in backlog doc).

**Canonical doc:** [`docs/por_transport_backlog.md`](por_transport_backlog.md)

**Core takeaway (already synthesized):** Freehold’s **reliable path is inline
relay forwarding**. Direct UDP / hole punch is an **optimization** when NAT
allows it — not the correctness path. P-OR should be **relay-first** with
optional direct hints, heartbeats as NAT keepalives, observed-address learning
from reverse path.

**Code skeleton (landed):** `por/peer_address.py` — register/challenge/confirm,
`PeerAddressRecord`, `build_dial_plan()`, privacy gates. Client planning now
uses records to choose a relay path when no explicit relay path is supplied.

**Remaining synthesis / implementation checklist** (assign to transport agent):

| Step | Status | Notes |
|------|--------|-------|
| Freehold commit/architecture review | **Done** | Snapshot in `por_transport_backlog.md` |
| P-OR adaptation spec (`PeerAddressRecord`, contact flow) | **Done** | Same doc |
| Compare Freehold SNAT/DNAT/XDP vs P-OR user-space constraint | **Open** | Explicit “what we skip” section exists; deepen with 1-page decision |
| DemuxSocket / shared UDP port pattern for `por` | **Open** | Deferred item #5 in backlog |
| Local UDP registration heartbeat demo (2 processes) | **Open** | Backlog item #2 |
| Wire `build_dial_plan()` into `por/client.py` | **Done (planning)** | Relay-first; no packet IO changes |
| Supernode + `peer_address` in one config | **Done (schema)** | Behavior still limited to planning flags |

**Owner:** transport/NAT agent for implementation. **Security review:** coordination
(composer agent, 2026-05-30) — see `docs/supernode_threat_model.md` Review outcome.
**D2–D4 unblocked; D5 blocked.**

**Rule:** NAT/peer-address work stays **below discovery, above Outfox bytes** —
never parse prompts, expertise, provider metadata, or circuit packets.

---

## Terminology (read before assigning work)

Network path stays **client → relay(s) → expert**. Relays/experts are peers
on the mixnet; “supernode” means your client also performs relay (and
eventually expert) duties when promoted.

| Avoid | Prefer |
|-------|--------|
| “gateway node”, separate gateway binary | **Same client binary**; optional local HTTP/SSE listener |
| `ROLE_GATEWAY` as a mixnet hop | **Client-local HTTP/SSE surface** (legacy config name TBD) |
| User chooses “client vs gateway install” | **One install**; supernode = public IP + config promotion |
| Wrapping `udp_demo` / `quic_demo` | Wire against **`por/client.py`** / unified client binary |

Naming cleanup (config roles, entrypoint names) is **deferred** — semantics
above are what matter for coordination today.

---

## Blocking coordination notes

These are **hard constraints** for parallel work. Violations block merge.

### A1 daemon team

- Finish daemon cleanup **without changing the Layer 7 contract**.
- `por-client` must keep using `prepare_expert_mode_request()` and must **not**
  grow a second envelope builder.
- If you change config shape, update **`por/config.py` only**. Do not fork
  per-daemon config formats.

**Audit (2026-05-30):**

| Check | Status |
|-------|--------|
| `por/client.py` → `prepare_expert_mode_request()` | OK |
| `por/daemon/client.py` → `run_client_once()` | OK |
| `por/quic_demo.py` second envelope builder | **Fixed** — uses `prepared.envelope` |
| Config only in `por/config.py` | OK |

### Wire lead — **critical path**

Land **A2/A3** before HTTP/SSE edge and NAT work depend on wire shape:

1. Replace JSON/base64 process framing with canonical **`0x00` forward** and
   **`0x01` return** carrier in `WireNodeRuntime` / daemons.
2. Remove **POR1** from the production path once native Outfox circuit setup is
   stable (compat bridge may stay in harness tests only).
3. Keep **`prepared.envelope`** as the only app payload on wire.
4. Extend **process-wire A5** coverage — not just in-process `test_a5_exit.py`.

**Status:** binary wire is the default path. JSON/base64 remains compatibility
harness code; new runtime features must not depend on it.

### HTTP/SSE local interface (Milestone C — same binary)

- **Do not** ship a separate gateway binary or wrap `udp_demo`.
- Add **optional local HTTP/SSE listen** on the **same client process** that
  already calls `prepare_expert_mode_request()` / send path.
- HTTP/SSE in → client send path out. Not a mix hop, not a second routing
  harness.

**Status:** local HTTP/SSE adapter exists on the same client process and emits
`chunk` events as circuit chunks are decrypted. It also emits final `message`
and `done` events for clients that want request metadata.

### Peer-address owner

- Stay **below discovery, above transport**.
- Wire `por/peer_address.py` into **client dial planning** only.
- **Do not** parse prompts, expertise labels, provider metadata, or circuit packets.
- **Relay-first**; direct UDP only as policy-controlled optimization.

**Status:** peer-address records are used by client route planning to select a
relay path when the request has no explicit relay path. Direct UDP remains
policy-gated and deferred from the send path.

### Logging / replay owner

- Move structured logs from **`por/log_events.py` helper** into actual
  relay/expert/client code paths.
- **Decide replay policy:** RAM-only circuits with explicit failure semantics
  **or** bounded persisted circuit-table state.

**Status:** unified config surfaces and runtime hot paths emit structured JSON
events. Replay policy is documented in `docs/replay_policy.md`; MVP circuit
state is RAM-only with explicit failure events.

---

## Live snapshot

| Area | Status | Owner |
|------|--------|-------|
| `por-relay` / `por-expert` daemons | Landed; UDP process smoke green | Composer (A1) |
| `por/provider.py` harness + Anthropic/OpenAI | Landed; default harness | Composer (A4) |
| `por/config.py` schema | **Done** — `PorConfig`, supernode, peer_address, local_http | Shared |
| Directory service v1 | File/HTTP snapshot + `por directory` / `por run` role | B |
| QUIC TLS policy | Secure default; dev opt-in for localhost certs | D |
| POR1 ↔ native circuit bridge | **POR1 removed from prod path**; native only | Wire (A2) |
| `por/client.py` + `por/daemon/client.py` | One-shot + `por run --config` client; binary send/recv | Runtime + wire |
| Wire end-to-end coverage (relay→expert→client) | **Done** — superseded the `test_a5_*` files; now `test_por_wire.py` (threaded on harness + subprocess CLI smoke) | Wire |
| `_find_exit_entry` + CI gate | Done | Wire (E) |
| Canonical `0x00`/`0x01`/`0x02` on process wire | **Done** — default daemon/client path | Wire (A2) |
| Only `prepared.envelope` on wire | **Done** — audit clean | Wire (A3) |
| Unified **`por`** binary CLI | **Done** — `send\|relay\|expert\|directory\|run` | A1 |
| Freehold NAT synthesis | Parked; peer-address planning + trusted relay dial target wired; hardening open | Transport (D) |
| `por run --config` single-file runtime | **Done** — relay/expert/client/directory | Runtime |
| Local HTTP/SSE client adapter | **Done** — chunk SSE from circuit callback | Runtime (C) |
| Supernode behavior | **Partial** — promoted daemon + inline forward covered by product gate; hardening open | Transport (D) |
| Persistent client loop | **Done (MVP)** — process session reused across requests | Runtime |
| End-user NAT (“download, run at home”) | **Partial** — trusted relay dial target + product gate; bundled defaults/hardening open | Transport (D) |

**Latest local verification:** `python3 -m pytest -q` — **180 passed, 0
failures**; coverage of `por/` is **79%** (`--cov=por`, floor 78 in
`pytest.ini`). `python3 scripts/check_ta_claims.py` — TA-3 OK.

> **Test toolchain (2026-05-30):** integration tests now run on
> `tests/harness.py` (`mixnet_harness`, `wire_cluster`, `static_wire_cluster`) —
> bind-once / hold-open sockets and joined serve threads. The previously flaky
> home-client gate was a cross-test port-reuse race from the old
> `reserve_udp_ports` bind-then-close idiom (now confined to the subprocess CLI
> smoke test). The legacy JSON/POR1 wire path was deleted from
> `node_runtime.py`. See the latest coordination-log entry.

## Conflict zones (coordinate before editing)

| File | Who touches it | Rule |
|------|----------------|------|
| `por/node_runtime.py` | Runtime + wire lead | Do not change recv/send framing without wire-owner review |
| `por/client.py` | Runtime + wire lead (A3) | Client sends `prepared.envelope` only; peer-address may plan relays but not parse payloads |
| `por/config.py` | Everyone on A1 | Extend schema; do not fork per-daemon config shapes |
| `por/udp_demo.py` / `por/quic_demo.py` | Harness only; JSON compat path | Not production daemons |

## Claimed — Composer (this agent)

| Item | Notes |
|------|--------|
| **A1: `por-relay` daemon** | `por/daemon/relay.py`, `WireNodeRuntime`, entry point `por-relay` |
| **A1: `por-expert` daemon** | `por/daemon/expert.py`, provider at exit |
| **A1: `por-client` daemon** | `por/daemon/client.py`, one-shot CLI, uses `prepare_expert_mode_request()` |
| **A1: Shared config schema** | `por/config.py`, shared cluster and daemon config shapes |
| **A4: Real LLM at expert exit** | `por/provider.py` |
| **A4: Provider errors + frontier fallback** | Same module; client frontier when `use_expert=false` |
| **Bridge: POR1 + native circuit install** | `build_por1_forward_plan`, `build_native_forward_plan`, runtime dual-path |
| **B: Directory service v1** | `load_public_snapshot_directory()` supports file/HTTP; `por-directory` serves snapshots |
| **D: TLS on by default** | `por/quic_transport.py`; `verify_tls=False` requires `dev_allow_insecure_tls=True` |
| **Runtime config convergence** | `por.config.v1` KEM identity, client options, supernode flags, cluster view |
| **C: HTTP/SSE on same client binary** | `client.local_http.enabled` on `por run`, no gateway binary |
| **D: `peer_address` wired** | Peer-address records can choose relay path before send |

Composer is **not** taking wire-lead items below.

## Assigned — wire lead

| Item | Notes |
|------|--------|
| A2: Outfox-native circuit setup on wire | Default client already native; remove POR1 from prod when ready |
| A2: Canonical `0x00`/`0x01` carrier | Landed on default daemon/client path; keep compatibility contained |
| A3: Only `prepared.envelope` on wire | Align with `por/client.py` send path |
| A5: Exit test end-to-end | `test_a5_exit.py` started — extend to process-wire if needed |
| E: `_find_exit_entry` hardening | `sphinxmix/mixnet.py` — commit on branch |
| E: CI = pytest + `check_ta_claims` | `scripts/check_ta_claims.py` |

## Owned backlog — assign or implement after A

| Item | Notes for assignee |
|------|-------------------|
| **A1: `por-client` daemon polish** | Persistent connections, edge adapter hookup, operator docs |
| **B: TA-2 pacing from envelope** | Wire `PacedCircuitStream` at expert when descriptor requests pacing |
| **C: HTTP/SSE token streaming** | Done for circuit chunks; provider-native token granularity depends on provider chunking |
| **Supernode promotion behavior** | Directory registration / relay advertisement observable; inline forwarding still open |
| **D: direct peer-address dialing** | Relay planning exists; direct UDP remains policy-gated and not used by send path |
| **D: Freehold NAT synthesis (finish)** | Deepen `por_transport_backlog.md`; DemuxSocket note; registration demo |
| **E: Structured logging rollout** | Runtime hot path now emits `PorLogEvent` JSON |
| **E: Relay restart/replay policy** | RAM-only MVP documented in `docs/replay_policy.md` |

## Codex-started (verify owner)

- `por/directory.py` — public snapshot provider
- `por/log_events.py` — structured log helper

## Sequencing

The client daemon should depend on `por/config.py`,
`prepare_expert_mode_request()`, the directory snapshot provider, and the wire
API that wire lead lands. It should not build a second application envelope.

Optional local HTTP/SSE on the **same client binary** should call the same send
path after wire lands. Reuse streaming shape from
`sim_mixnet_anthropic_proxy.py`; that proxy remains an in-process harness.

Peer address work stays below the route planner and above the raw transport. It
must not parse prompts, expertise labels, provider metadata, or circuit packet
contents.

## Monitoring

While teams work in parallel, run from repo root:

```bash
bash scripts/watch_por_changes.sh
```

Wakes on changes under `por/`, Outfox wire files, A5/UDP tests, and this doc.

---

## Coordination log

Append-only updates. **Wire team:** read blocking notes above + latest entry
here before starting work.

### 2026-05-30 — Test toolchain rebuild + flake root-cause (coordination handoff)

- **Flake root-caused.** The home-client gate (`test_home_client`) was flaky —
  passed in isolation, failed ~1/80 under full-suite load with a return-path
  `TimeoutError` and a relay `forward_expired_or_invalid`. Cause: cross-test UDP
  port reuse from the `reserve_udp_ports` **bind-then-close** idiom (helpers.py)
  plus daemon serve threads that were never `join()`ed — stray datagrams hit
  recycled ephemeral ports. **Not** a crypto/timestamp bug.
- **Durable harness** (`tests/harness.py`): `mixnet_harness` /`wire_cluster` /
  `static_wire_cluster`. Bind-once, hold-open sockets; `Event`-stopped, joined
  serve threads. Runtime gained `serve_on_socket()` so production `serve_forever`
  and the harness drive the **same** loop. `run_client_once` /
  `send_prepared_envelope` accept a caller-owned `client_sock`.
- **`reserve_udp_ports` scoped to subprocess-only** (CLI smoke test) and
  documented; all in-process tests migrated off it.
- **Deleted the legacy JSON/base64 + POR1 wire path** from `node_runtime.py`
  (binary `0x00/0x01/0x02` is the only path). `binary_wire=` flag removed from
  `serve_forever`. node_runtime coverage **51% → 82%**.
- **Consolidated** `test_por_supernode.py`: removed a 116-line test that
  re-implemented the relay/expert with raw `outfox_process` (never exercised the
  real `SupernodeDaemon`); replaced with real-daemon opaque NAT-return tests.
- **Coverage gate**: `por/` at **79%**; `pytest.ini` floor raised 72 → 78.
- **Result:** `pytest -q` → **180 passed, 0 failures**, deterministic across
  repeated full-suite runs. **T3/T4 are now genuinely green** (the prior agent's
  "done" was a single lucky run on the flaky gate).

### 2026-05-30 — Product runtime pass (persistent client + SSE)

- **Persistent client session**: `por run` client local HTTP mode now keeps one
  in-process `PersistentClientSession`, reusing loaded config, directory
  snapshot, and request machinery across prompts. No subprocess-per-request.
- **Token SSE / status**: local HTTP/SSE writes `chunk` events from the circuit
  receive callback as chunks decrypt, then emits final `message` and `done`
  metadata. `/healthz` and `client.local_http.status_path` expose JSON session
  counters for operators.
- **Hot-path logging**: `WireNodeRuntime` relay/expert recv/send decisions now
  use `PorLogEvent` JSON (`forward_hop`, `expert_exit`, `circuit_hop`,
  `circuit_replay`, etc.) instead of plain `print()`.
- **Supernode directory behavior**: `supernode.register_directory` now produces
  observable `supernodes` records in directory snapshots with relay handles.
- **Replay policy**: MVP is RAM-only circuit state; restart drops circuits,
  replay/malformed/missing packets are logged and dropped.
- **Did not touch**: binary recv/send framing; no `udp_demo` / `quic_demo`
  product wrapping; no separate gateway binary.

### 2026-05-30 — Runtime landed (config + boundaries; wire untouched)

- **`por run --config`**: one `por.config.v1` dispatches relay, expert, client,
  directory. Shared client config, local HTTP/SSE, peer-address records,
  supernode promotion flags.
- **Peer-address**: `build_dial_plan()` → relay path in client **planning only**
  (no direct UDP dial, no supernode endpoint IO).
- **Local HTTP/SSE**: same client process; SSE emits **completed** response today
  (token streaming deferred).
- **Logging**: structured events at config startup + request boundaries; hot
  runtime path still mostly `print()`.
- **Did not touch**: recv/send framing after wire PR1; did not wrap `udp_demo`.
- **135 tests**, TA-3 OK.
- **Explicit open**: token SSE streaming, peer-address transport dial, supernode
  inline forward behavior, hot-path logging, persistent client loop.

### 2026-05-30 — Wire lead (PR1+PR2+PR4 landed)

- **Binary 0x00/0x01/0x02 carrier landed** in `por/wire_frame.py`. Daemons
  default to `binary_wire=True`. JSON path retained for harness compat only.
- **`WireNodeRuntime`**: binary dispatch via `_dispatch_binary` → `_handle_forward_binary` /
  `_handle_circuit_binary`. Raw UDP datagrams, no base64, no JSON on production path.
- **`por/client.py`**: `send_prepared_envelope` uses `encode_forward` + `decode_datagram`.
  Removed `circuit_wire` param — native Outfox circuit setup is the only path.
- **POR1 removed from prod**: `circuit_wire="por1"` param deleted. POR1 bridge test deleted.
  Legacy `build_por1_forward_plan` may remain in `node_runtime.py` for reference only.
- **`test_a5_process_wire.py`**: spawns relay+expert subprocesses with binary wire,
  sends 0x00 forward, receives 0x01 circuit stream, verifies prompt visibility.
- **135 tests green**, pushed to remote master.
- **Unblocked**: Gateway team can wrap `send_prepared_envelope`. Peer-address can
  plug into client dial below discovery. Logging team can swap `print()` for
  `por/log_events.py` — event names are stable.

### 2026-05-30 — Composer

- **Doc is source of truth** for cross-team coordination; wire bill of work
  distilled into blocking notes + wire-lead section above.
- **Terminology:** dropped “gateway node” framing; Milestone C is an HTTP/SSE
  **edge adapter**, not a new hop type. File/role renames deferred.
- **A1 audit:** `por/client.py` and `por/daemon/client.py` OK on Layer 7
  contract; `quic_demo` fixed to use `prepared.envelope` (no second builder).
- **Wire critical path unchanged:** JSON/base64 still in `WireNodeRuntime`;
  binary `0x00`/`0x01` + process-wire A5 still open.
- **Tests:** `pytest -q` 105 passed; `check_ta_claims.py` TA-3 OK.
- **Still not production:** persistent connections/NAT, HTTP/SSE edge adapter,
  prompt hiding/PoE, canonical wire on daemons (see README “What doesn’t exist
  yet”).

### 2026-05-30 — Check-in (Composer)

- **Tests:** 120 passed (+15 since last log); TA-3 OK.
- **Wire A2:** `por/wire_frame.py` added (encode/decode `0x00`/`0x01`/`0x02`) but
  **not yet integrated** — `WireNodeRuntime` and `por/client.py` still use
  JSON/base64 on the hot path. Wire team should finish hookup + process-wire A5.
- **Uncommitted local work:** `wire_frame.py` untracked; minor edits on
  `client.py`, `node_runtime.py`, demos (coordination-only doc + quic envelope fix).
- **Still blocked on wire:** HTTP/SSE edge adapter, peer-address dial integration,
  production persistent connections/NAT, prompt hiding/PoE.
- **A1 contract:** still OK — client path uses `prepare_expert_mode_request()` only.

### 2026-05-30 — Product stance (owner)

- **One binary for everyone** — no separate gateway install or gateway node type.
- **Supernode** = same binary, promoted when operator has a **public IP** (relay
  for others, directory registration); not a different product SKU.
- **HTTP/SSE** = optional **local interface** on that client (localhost/provider
  streaming), not a mix hop or second binary.
- Milestone A **`por-relay` / `por-expert` CLI splits** are interim harness/dev
  only; converge on unified client + supernode config over time.

### 2026-05-30 — Unified binary landed (Composer)

- **`por`** is the primary entry point: `send`, `relay`, `expert`, `directory`, `run`.
- **`python -m por`** and `setup.py` console script `por=por.daemon.main:main`.
- Legacy **`por-relay` / `por-expert` / `por-client`** delegate with deprecation stderr.
- **`udp_demo`** harness spawns `python -m por relay|expert` (not separate modules).
- **Convergence checklist** added above — remaining: `por run` for relay/expert from
  single config, persistent client, supernode flags, remove legacy names.
- **Tests:** `tests/test_por_unified_binary.py` + full suite should stay green.

### 2026-05-30 — Full review (Composer)

- **124 pytest passed**; TA-3 OK. **~15 files uncommitted** (unified `por`, `wire_frame.py`, convergence doc).
- **Critical path:** wire A2 still open — `wire_frame.py` exists but **not hooked**; runtime docstring says binary, loop still JSON.
- **Two-agent split** recommended: **Agent Wire** (A2/A3/A5) then **Agent Runtime** (config unify, persistent client, peer_address, logging, local HTTP/SSE) — see team briefing in chat / assign from blocking notes.
- **Not production:** NAT/persistent sessions, prompt hiding/PoE, binary daemon wire, `por run` single-config supernode.

### 2026-05-30 — Pre-train handoff (Composer)

- **Committed:** unified `por` CLI, `wire_frame.py`, convergence doc, quic envelope fix.
- **Docstring fix:** `node_runtime` honestly documents JSON harness until A2 integration.
- **Added:** `tests/test_wire_frame.py` (framing prep only).
- **Runtime gate:** HTTP/SSE + NAT blocked until binary wire merges (see above).
- **Wire agent next:** integrate `wire_frame` into runtime + client + `test_a5_process_wire`.

### 2026-05-30 — Freehold NAT track parked (owner)

- Agent review of **maceip/freehold** synthesized into `docs/por_transport_backlog.md`
  (relay-first, inline fallback, heartbeats, observed NAT port, no XDP requirement).
- **`por/peer_address.py`** matches that spec and feeds client dial planning;
  actual supernode socket IO still belongs to Transport D2/D3.
- **Not dropped:** pinned under “Parked — Freehold NAT synthesis” in
  `production_arc.md`. Transport IO for the resolved supernode target remains
  open; **research/doc** may continue (DemuxSocket comparison, registration demo
  design).

### 2026-05-30 — Runtime config convergence

- **`por run --config`** can dispatch relay, expert, and client roles from one
  `por.config.v1` file. Relay/expert daemon config now carries KEM identity and
  can produce the existing cluster runtime view.
- **Supernode promotion flags** landed in config schema: public IP,
  relay advertisement, directory registration, inbound mix acceptance, and
  future expert promotion. Behavior beyond flags is still open.
- **Peer-address planning** is wired into `por/client.py`: records may choose a
  relay path when the caller did not provide one. Records must be signed by a
  trusted reachability relay before they can influence a dial. Direct UDP stays
  deferred.
- **Local HTTP/SSE** landed as an optional same-process client adapter via
  `client.local_http.enabled`; no new gateway binary.
- **Structured logging** now covers unified config startup/request boundaries and
  runtime packet hot paths.

### 2026-05-30 — End-user connectivity bar (owner, remember)

- Shipped client must **run at home with no port-forwarding or peer IP paste** —
  download, run, send a prompt. That is the product test; extensions can wait.
- Implies: bundled directory + default supernode(s), client never needs inbound
  UDP; NAT'd experts reachable via inline relay (see `por_transport_backlog.md`).
- MVP path now resolves verified peer-address dial targets to trusted relays;
  bundled defaults and production hardening remain open.
- Keep in Milestone D / Freehold track — do not drop; no new doc elevation.

### 2026-05-30 — Milestone D1 landed (transport; pending security review)

- **`docs/supernode_threat_model.md`** — reachability-only role, correlation risks,
  mandated constraints, implementation order (security gate).
- **`por/supernode.py`** — `SupernodeForwarder` **lookup table** (TTL, heartbeat,
  peer→addr). **Not** a daemon receive→forward loop yet; `run_supernode_forwarder()`
  is a stub. Tests prove the hop **architecture** via manual forward.
- **Tests:** `tests/test_por_supernode.py`.
- **Agreed status (owner):** D1 = table + threat model + architectural proof —
  **not** “NAT done” and **not** wired into `por run`.
- **Open for security review:** MVP accepts bootstrap supernode correlation;
  demux story (one socket vs reachability vs mix) must be chosen before D2 daemon.
- **After threat-model sign-off:** D2 forward loop + relay UDP control plane;
  D3 client dials resolved supernode endpoint; D5 bundled defaults **last**;
  D6 acceptance = `por send` with defaults only.
- **Planning wired:** `build_dial_plan()` in `por/client.py` verifies trusted
  records before they can influence route planning. Transport IO is still open.

### 2026-05-30 — Supernode security review (coordination)

- **Reviewer:** architecture coordination (composer — wrote the gate).
- **Verdict:** **conditional approve** — D2–D4 may proceed; **D5 defaults blocked**.
- **Demux closed:** one UDP bind; REACH control → mix runtime → opaque NAT forward.
- **D2 conditions:** no Layer 7 imports on forward path; registration rate limits;
  metadata-only logs.
- **Before D5:** signature verify on dial, PeerAddressRecord in directory per expert,
  `trusted_reachability_relays` in client config, security regression tests.
  The client-side trust/directory/dial-plan pieces have landed; bundled defaults
  remain blocked until the transport plugs the resolved target into real IO.
