# P-OR Production Arc

Status: coordination note for current Python work. This is not a privacy claim
or release checklist.

**Last updated:** 2026-05-30 (client daemon/send path smoke green)

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
| Canonical `0x00`/`0x01` on process wire | Not started (JSON/base64 still) | Wire lead (A2) |
| Only `prepared.envelope` on wire | Partial (`client` uses orchestrator) | Wire lead (A3) |

**Latest local verification:** `python3 -m pytest -q` — 102 passed;
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
| **A1: `por-client` daemon polish** | Persistent mode, gateway integration, more operator docs |
| **B: TA-2 pacing from envelope** | Wire `PacedCircuitStream` at expert when descriptor requests pacing |
| **C: `por-gateway` HTTP/SSE** | After client daemon; pattern from `sim_mixnet_anthropic_proxy.py` |
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

The gateway should wrap the client daemon after the daemon send path exists. It
should reuse the streaming shape from `sim_mixnet_anthropic_proxy.py`, but that
proxy remains an in-process harness.

Peer address work stays below the route planner and above the raw transport. It
must not parse prompts, expertise labels, provider metadata, or circuit packet
contents.

## Monitoring

While teams work in parallel, run from repo root:

```bash
bash scripts/watch_por_changes.sh
```

Wakes on changes under `por/`, Outfox wire files, A5/UDP tests, and this doc.
