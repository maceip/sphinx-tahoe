# P-OR Production Arc

**This file is the coordination doc.** All parallel teams check here for
constraints, ownership, and status. New updates go in
**[Coordination log](#coordination-log)** at the bottom.

Status: coordination note for current Python work. This is not a privacy claim
or release checklist.

**Last updated:** 2026-05-30 (product stance: one binary)

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
| **`por run --config`** from single `por.config.v1` for relay/expert | **Open** — needs kem keys in daemon schema | A1 + wire |
| Persistent client loop (`por run`, role=client) | **Open** | A1 |
| Supernode promotion flags in one config file | **Open** — public IP + relay registration | A1 + D |
| Local HTTP/SSE on client process (not separate binary) | **Open** | C |
| Remove legacy console script names | **Open** — after one release cycle | A1 |

**Gate:** do not add new top-level console scripts. New behavior → **`por` subcommand** or config flag on the same binary.

### Runtime agent gate (until binary wire merges)

**Do not start** on the Runtime track until Wire lands binary framing in
``WireNodeRuntime`` + ``por/client.py`` (process-wire A5 green):

- Local HTTP/SSE listener on `por`
- NAT / peer-address dial integration in client
- Persistent client session loop that assumes production wire shape

Runtime **may** prep in parallel: ``por.config.v1`` schema (kem keys), structured
logging helpers, replay policy **doc only** — no recv/send path changes.

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

**Still open:** JSON recv loop still in `WireNodeRuntime.serve_forever()`; wire
team must wire `por/wire_frame.py` into runtime + client and land tests.

### HTTP/SSE local interface (Milestone C — same binary)

- **Do not** ship a separate gateway binary or wrap `udp_demo`.
- Add **optional local HTTP/SSE listen** on the **same client process** that
  already calls `prepare_expert_mode_request()` / send path.
- HTTP/SSE in → client send path out. Not a mix hop, not a second routing
  harness.

**Still open:** no local HTTP/SSE listener on unified client yet; use
`sim_mixnet_anthropic_proxy.py` only as a streaming pattern reference.

### Peer-address owner

- Stay **below discovery, above transport**.
- Wire `por/peer_address.py` into **client dial planning** only.
- **Do not** parse prompts, expertise labels, provider metadata, or circuit packets.
- **Relay-first**; direct UDP only as policy-controlled optimization.

**Still open:** skeleton only; not in client dial path.

### Logging / replay owner

- Move structured logs from **`por/log_events.py` helper** into actual
  relay/expert/client code paths.
- **Decide replay policy:** RAM-only circuits with explicit failure semantics
  **or** bounded persisted circuit-table state.

**Still open:** daemons use plain `print()`; no replay policy doc.

---

## Live snapshot

| Area | Status | Owner |
|------|--------|-------|
| `por-relay` / `por-expert` daemons | Landed; UDP process smoke green | Composer (A1) |
| `por/provider.py` harness + Anthropic/OpenAI | Landed; default harness | Composer (A4) |
| POR1 ↔ native circuit bridge | Native is default; POR1 remains compat-only | Composer (bridge until wire finishes A2) |
| `por/client.py` + `por/daemon/client.py` | Minimal one-shot client landed; process-node smoke green | Codex (A1) |
| `por/config.py` schema | Expanded (`ClusterConfig`, `DaemonConfig`) | Codex / shared A1 |
| Directory service v1 | File/HTTP public snapshot loading + `por-directory` server landed | Codex (B) |
| QUIC TLS policy | Secure default landed; insecure localhost requires dev opt-in | Codex (D) |
| `test_a5_exit.py` in-process native path | Landed (no JSON frames) | Wire lead (A5) |
| `_find_exit_entry` + CI gate | Commit `40be4cf` on branch | Wire lead (E) |
| Canonical `0x00`/`0x01` on process wire | **Prep only** — `por/wire_frame.py` + tests; runtime/client still JSON | Wire lead (A2) |
| Unified **`por`** binary CLI | **Done** — `send\|relay\|expert\|directory\|run` | A1 |
| Only `prepared.envelope` on wire | Partial (`client` uses orchestrator) | Wire lead (A3) |

**Latest local verification:** `python3 -m pytest -q` — 124 passed;
`python3 scripts/check_ta_claims.py` — TA-3 OK.

## Conflict zones (coordinate before editing)

| File | Who touches it | Rule |
|------|----------------|------|
| `por/node_runtime.py` | Composer + wire lead | Keep dual POR1 + `on_circuit` until wire lead drops POR1 from prod path |
| `por/client.py` | Composer + wire lead (A3) | Client sends `prepared.envelope` only; no second envelope builder |
| `por/config.py` | Everyone on A1 | Extend schema; do not fork per-daemon config shapes |
| `por/udp_demo.py` / `por/quic_demo.py` | Harness only | Wire lead replaces framing here when A2 lands; not production daemons |

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

Composer is **not** taking wire-lead items below.

## Assigned — wire lead

| Item | Notes |
|------|--------|
| A2: Outfox-native circuit setup on wire | Default client already native; remove POR1 from prod when ready |
| A2: Canonical `0x00`/`0x01` carrier | Replace JSON/base64 harness framing in daemon wire path |
| A3: Only `prepared.envelope` on wire | Align with `por/client.py` send path |
| A5: Exit test end-to-end | `test_a5_exit.py` started — extend to process-wire if needed |
| E: `_find_exit_entry` hardening | `sphinxmix/mixnet.py` — commit on branch |
| E: CI = pytest + `check_ta_claims` | `scripts/check_ta_claims.py` |

## Owned backlog — assign or implement after A

| Item | Notes for assignee |
|------|-------------------|
| **A1: `por-client` daemon polish** | Persistent connections, edge adapter hookup, operator docs |
| **B: TA-2 pacing from envelope** | Wire `PacedCircuitStream` at expert when descriptor requests pacing |
| **C: HTTP/SSE on same client binary** | Optional local listener; pattern from `sim_mixnet_anthropic_proxy.py` |
| **Supernode promotion** | Public IP + config → relay (and later expert) duties in same binary |
| **D: `peer_address` wired** | `por/peer_address.py` → client dial plan |
| **E: Structured logging rollout** | `por/log_events.py` → apply across daemons |
| **E: Relay restart/replay policy** | Optional `CircuitTable` persistence design |

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
