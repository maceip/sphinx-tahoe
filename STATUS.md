# tenet / sphinx-tahoe — STATUS

**The only living document for planning, design, status, and TODO.**

Last re-verified: **2026-06-04** (live `por enclave send`, process table, Nitro relay/TEE, configs, expert log, `deploy/data/beta/`)

Superseded markdown: `~/fat/tenet-archive/` — do not treat as current.

---

## Containment

This file is the authority. Do not create new gates, phases, branch labels, or side runbooks. Use the queue IDs below.

Current beta path: **one matcher-only Nitro TEE + one public REACH relay + one off-TEE laptop expert + direct client relay send**.

Legacy filenames containing `gate-b` are operational script names only. Do not add new `gate-*` or `phase-*` concepts unless replacing those filenames with item-numbered names.

Pytest is not live-network proof. The only accepted runtime proof for item **13** is direct `por enclave check`, `por enclave match`, and `por enclave send` against `config/live-enclave.json`.

## Implementation queue

**Use only these IDs** in commits and comments (`STATUS.md 11`, not “gate B”).

| ID | Work | Status | Blocked by | Blocks |
|----|------|--------|------------|--------|
| **1** | Opaque handles + directory (no public mailbox map) | **Done** | — | 2, 8 |
| **2** | Matcher/mailbox wire shape (`/v1/match`, handles, deliver) | **Done** | 1 | 6, 8 |
| **3** | Outfox + wire daemon (sealed-transport plumbing) | **Done** | — | 13 |
| **4** | Attestation (`aw check --json`, policy, fail-closed) | **Done** | 2 | 5, 9, 13 |
| **5** | SPKI pin on enclave-plane TLS | **Done** | 4 | 9, 13 |
| **6** | Oblivious matcher (top-K + cover handles) | **Done** | 2 | 7, 9 |
| **7** | Rust oblivious selector in TEE image | **Done** | 6 | 9 |
| **8** | Enclave plane server (loopback workload) | **Done** | 1, 2 | 9 |
| **9** | Live Nitro TEE + attested TLS + DNS | **Done** | 4, 5, 7, 8 | 11–15 |
| **10** | Reachability-relay security tests | **Done** | — | R3 |
| **11** | Public reachability relay (REACH + forward) | **Done** | 9 | 12, 13, 15 |
| **12** | Expert: REACH register + manifest on laptop | **Done (single laptop expert)** | — | 13 |
| **13** | Asker: attested match → relay → remote expert → real reply | **Done (single-expert live path)** | — | 14, 15 |
| **14** | Matcher-only TEE image (no in-TEE stub expert fleet) | **Done** | — | — |
| **15** | Network beta: ≥2 humans, stable pins, run notes | **Open** | 13 | — |

**Rules (not queue IDs):**

| Rule | Text |
|------|------|
| **R1** | Security level is network-wide, never per-user |
| **R2** | Migration flips the whole network, never two live trust models |
| **R3** | No bundled default reachability-relay URLs in the repo until item **10** passed |

**Engineering shortcuts (item 9 only, not product):** in-TEE stub relay/expert in `deploy/run_matcher_live.py`, stub `por enclave send` reply, `./scripts/demo-mailbox-e2e.sh`.

**Still open after item 13:** repeat/load hardening, larger multi-packet returns above the current `POR_MAX_TOKENS=128` cap, second human, and dirty-tree/script consolidation.

**Off critical path (no queue ID):** expert groups taxonomy (`por/expert_groups.py`), Android (`android/`), ARC credentials.

---

## Verified right now (2026-06-04)

| What | Truth |
|------|--------|
| Matcher URL + pins | `config/live-enclave.json` → **`https://7d90e638b585.aeon.site/`**, Value X `7d90e638b585…`, SPKI `d8d8398b6e4bbbb2…`, `aw` @ `79a5ea2` |
| Nitro parent | `3.121.69.82`, instance `tenet-matcher-nitro` (`i-069a473107424b7df`, eu-central-1), SSH `~/.ssh/tenet-nitro.pem` |
| Reach relay (item 11) | UDP **4433** on `3.121.69.82`; config `config/live-reach-relay.json`; process `python3 -m por run --config config/live-reach-relay.json --node-id reach-beta-1`; return-session + stale-address cleanup deployed |
| Expert (item 12) | Laptop expert **`hb85f9afbccddfe5`**, `config/expert-laptop.json`, screen `por-expert`, Fry-core `ANTHROPIC_API_KEY`, `claude-sonnet-4-6`, `POR_MAX_TOKENS=128`, REACH heartbeats OK to relay; **UPnP failed** on Mac |
| TEE beta data | `deploy/data/beta/snapshot.json` + `deploy/data/beta/mailbox.json` handle **`hb85f9afbccddfe5`** (matches laptop expert); peer-address TTL **86400s** |
| Asker (item 13) | `por enclave send` **proved 2026-06-04**: `ok: true`, selected `hb85f9afbccddfe5`, real Claude text, `fallback_used: false`, `via_mailbox: false` |
| Item 14 | Matcher-only entry `deploy/entry-matcher.sh`; EIF names `matcher-gate-b` / `matcher-beta*` on Nitro |
| Item 15 | Not started: second human + repeat/load beta notes still open |
| **Alpha network** | Required for item **15** scale-out, not required for the current single-expert item **13** proof. Population materialized locally (`config/alpha-population.json`, **9** experts from agent logs + seeds). **Not** deployed at scale on separate nodes yet. Code: `por/alpha_experts.py`, `scripts/alpha/materialize-experts.py` |

Last direct proof command:

```bash
env PATH=/Users/mac/.cargo/bin:$PATH python3 -m por enclave send \
  --config config/live-enclave.json \
  --mailbox-config config/live-mailbox-client.json \
  --prompt 'In one sentence, name one Monet painting technique.' \
  --timeout 120 --json
```

Result: `ok: true`, `selected_peer_id: hb85f9afbccddfe5`, real Claude response, `via_mailbox: false`.

`via_mailbox: false` is correct for the current matcher-only live path: the TEE returns the handle/peer route and the client sends directly through the REACH relay. `via_mailbox: true` applies only if TEE `/v1/deliver` datagram delivery is wired into the live image; that is not the current beta path.

**Do not cite pytest as proof the live network works.**

## Known remaining work

| Work | Owner ID | Truth |
|------|----------|-------|
| Second human / multi-human beta | **15** | Open |
| Repeat sends and load stability | **15** | Open; current single send works, but do not claim sustained beta stability yet |
| Larger responses | **15** | Open; current expert is capped with `POR_MAX_TOKENS=128` |
| Multi-node Alpha deployment | **15** | Open; local population exists, separate-node deployment not proven |
| Dirty-tree consolidation | — | Open; keep legitimate beta files, exclude secrets, retire stale docs/scripts deliberately |

---

## Alpha network (required for item 15 scale-out)

**Alpha** is the live expert **population**: peers built from permitted agent session logs (Cursor, Codex, Claude, Antigravity, etc.), each with a corpus under `data/alpha/corpus/` and a real `por run` on its **own** node (never colocated with the reach relay).

| Artifact | Role |
|----------|------|
| `config/alpha-population.json` | Expert IDs, corpus paths, descriptors (gitignored) |
| `data/alpha/groups.json` | `por.expert_groups` index (gitignored) |
| `scripts/alpha/materialize-experts.py` | Build population from logs |
| `scripts/alpha/run-alpha-network.sh` | Materialize → deploy on topology (uses `scripts/gate-b/*`) |

Synthetic seeds (`alpha-seed-*`) only pad node count when there are fewer sessions than VMs.

---

## Product topology

```
┌──────── TEE (Nitro) ─────────────────────────────────────────────┐
│  MATCHER (oblivious k-NN)              MAILBOX (oblivious route)   │
└────▲───────────────────────▲──────────────────────────│─────────┘
     │ query                 │ handles                     │ sealed
┌────┴─────┐                                    ┌──────────────────┐
│  ASKER   │◀───────────────────────────────────│ REACHABILITY     │
│  laptop  │── sealed via handle ────────────────▶│ relay (public)   │
└────▲─────┘                                    └─────────┬────────┘
     │ answer                                              │ sealed
     └────────────────────────────────────────────  ┌───────────┐
                                                      │  EXPERT   │
                                                      │  (laptop  │
                                                      │  or VM)   │
                                                      └───────────┘
```

**Invariant:** Expert is a person/machine **outside** the Nitro matcher image.

Code: `por/daemon/expert.py`, `por/reach_client.py`, `por/daemon/supernode.py`, `por/node_runtime.py` (supernode must `attach_socket` for REACH replies).

---

## Architecture (locked)

| Decision |
|----------|
| Single client binary (`python3 -m por`) |
| Single trust model: oblivious TEE matcher/mailbox |
| Lossy match OK; frontier model is correctness floor |
| Opaque embeddings only on disk/wire/directory |
| Wire-then-harden: HTTP stand-ins → attestation → SPKI → oblivious → TEE |

---

## Operations (items 11–15)

All commands live here; scripts do not carry a second copy of this plan.

### Secrets and configs

```bash
./scripts/init-beta-secrets.sh
# Set REACH_RELAY_HOST in config/beta-secrets.env
./scripts/render-beta-config.sh
```

Outputs: `config/live-reach-relay.json`, `config/live-mailbox-client.json`, `config/templates/expert-laptop.json` → patched `config/expert-laptop.json`.

### Item 11 — relay on public VM

```bash
python3 -m por run --config config/live-reach-relay.json --node-id reach-beta-1
./scripts/verify-reach-relay.sh
```

UDP **4433** open on the relay host.

### Item 12 — expert laptop

```bash
./scripts/expert-onboard.sh /path/to/corpus
# Patch opaque handle in config/expert-laptop.json (current: hb85f9afbccddfe5)
screen -dmS por-expert /bin/zsh -lc '
  set -a
  source /Users/mac/fry-core/.env
  set +a
  export POR_MAX_TOKENS=128
  cd /Users/mac/sphinx-tahoe
  exec python3 -m por run --config config/expert-laptop.json \
    --node-id hb85f9afbccddfe5 >>/tmp/por-expert.log 2>&1
'
```

Must log `reach_registered` and heartbeats. Current Mac expert: **REACH OK**, **UPnP failed**, delivery works through the public REACH relay after duplicate old expert processes are removed.

### Alpha — materialize population (before multi-node deploy)

```bash
./scripts/alpha/materialize-experts.py --write-groups
```

### Items 13–14 — sync TEE data and redeploy matcher

After expert handle + signed `peer_address` are stable:

```bash
./scripts/sync-gate-b-artifacts.py   # legacy filename; sync when relay + expert are up
./deploy/assemble-matcher-eif.sh
# Nitro: EIF=.../matcher-*.eif ./deploy/redeploy-matcher-eif.sh
# Update config/live-enclave.json if Value X / DNS changes
```

Default EIF entry: `deploy/entry-matcher.sh` (matcher-only, no stub fleet).

### Item 13 — asker proof

```bash
python3 -m por enclave send --config config/live-enclave.json \
  --mailbox-config config/live-mailbox-client.json \
  --prompt "..." --timeout 120 --json
```

Success for the current matcher-only beta path: `ok: true`, `fallback_used: false`, `via_mailbox: false`, real provider text (not stub).

If this times out, first check for duplicate local expert processes with the same handle:

```bash
ps -e -o pid,args | rg '[p]ython.*-m por run --config config/expert-laptop.json'
```

There should be exactly one Python expert child. Multiple children can race REACH registration and make the relay forward to the wrong local UDP socket.

### Multi-node deploy (relay ≠ expert hosts)

```bash
EXPERT_NODE_COUNT=3 ./scripts/alpha/run-alpha-network.sh
# or: scripts/gate-b/provision-network.sh → deploy-nodes.sh → verify-network.sh
```

Topology: `config/gate-b-topology.json.example` — experts must not share the relay host IP.

### Item 15 — human beta

Second human on asker; record URL, SPKI, `aw` SHA, relay host, handle prefix in **this file**. No asker↔expert direct IP.

### Matcher live (item 9) redeploy

```bash
ATTESTED_WORKLOAD_SHA=79a5ea2 ./deploy/build-bountynet-bin.sh
ATTESTED_WORKLOAD_SHA=79a5ea2 ./deploy/assemble-matcher-eif.sh
./deploy/redeploy-matcher-eif.sh
```

DNS: `{value_x[0:12]}.aeon.site` → Elastic IP. Redeploy **always** updates pins in `config/live-enclave.json` and this section.

| Deploy issue | Fix |
|--------------|-----|
| memory 3500 (E39) | 2048 MiB |
| proxy on :443 | root |
| ACME | root |
| old `aw` after ACME | install @ `79a5ea2` |

---

## Commands vs what they prove

| Command | Proves | Does not prove |
|---------|--------|----------------|
| `make smoke` | Repo logic | Live network |
| `./scripts/verify-live.sh` | Items **4, 5, 9** | Items **11–15** |
| `por enclave check` | **4, 5** on live URL | **13** |
| `por enclave match` / `plan` | **9** API | Human expert delivery |
| `por enclave send` | **13** when it returns `ok: true`, real provider text, and selected live expert handle | Repeat/load/human beta |
| `./scripts/demo-mailbox-e2e.sh` | Local harness | Anything live |
| `./scripts/gate-b/run-protocol-checks.sh` | Loopback protocol | Items **11–15** |
| `./scripts/alpha/run-alpha-network.sh` | Alpha + multi-node ops | **13** unless send succeeds |

Pytest: default excludes `live`; tiers in `scripts/test.sh`.

---

## Code map

| ID | Code | Tests |
|----|------|-------|
| 1 | `por/handles.py`, `por/directory.py` | `tests/test_por_directory_service.py` |
| 2 | `por/matcher.py`, `por/enclave_plane.py` | `tests/test_matcher_mailbox_linkage.py` |
| 3 | `sphinxmix/`, `por/node_runtime.py`, `por/daemon/` | `tests/test_outfox.py`, `tests/test_mixnet.py`, `tests/test_por_wire.py` |
| 4 | `por/enclave_attest.py` | `tests/test_enclave_attest.py` |
| 5 | `por/attested_transport.py` | `tests/test_attested_transport.py` |
| 6 | `por/oblivious.py`, `por/cover.py` | `tests/test_oblivious*.py` |
| 7 | `oblivious-core/` | `tests/test_oblivious_rust.py` |
| 8 | `por/enclave_plane_server.py` | `tests/test_enclave_plane_server.py` |
| 9 | `deploy/*`, `por/live_enclave.py` | `tests/test_live_enclave.py`, `./scripts/verify-live.sh` |
| 10 | `por/reach_client.py`, `por/daemon/supernode.py` | `tests/test_por_supernode_security.py`, `tests/test_reach_client.py` |
| 11 | `por/daemon/supernode.py` | live relay + `verify-reach-relay.sh` |
| 12 | `por/upnp.py`, `por/daemon/expert.py` | live expert REACH |
| 13 | `por/client.py`, `por/live_enclave.py` | live `por enclave send` |
| 14 | `deploy/entry-matcher.sh` | EIF inspect |
| 15 | — | human beta notes in this file |
| Alpha | `por/alpha_experts.py`, `scripts/alpha/` | `tests/test_alpha_experts.py` + live deploy |

---

## Retired labels (do not use in new prose)

| Old | Use instead |
|-----|-------------|
| Gate A, Bar A, milestone 3.1 | Items **1–9** done |
| Gate B, Bar B, milestone 3.2 | Items **11–15** (+ Alpha population) |
| B1–B6 | Items **10–15** |
| beta runbook / gate-b-network / alpha-network docs | **This file** (archived copies under `~/fat/tenet-archive/docs/`) |

---

## Vocabulary

| Say | Don't say |
|-----|-----------|
| item **N** | “gate B done”, “beta ready” without the number |
| reachability relay | “supernode” without context |
| engineering shortcut | “product e2e” for stub send |
| Alpha network | optional expert fleet |

---

## Repos

| Repo | Role |
|------|------|
| **sphinx-tahoe** | Product + deploy |
| **attested-workload** | `aw check`, Nitro proxy, attested TLS |
