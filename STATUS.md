# tenet / sphinx-tahoe — STATUS

**The only living document for planning, design, status, and TODO.**

Last re-verified: **2026-06-04** (live current-alpha `por ask`, 20/20 repeat/load, fresh EC2 asker, bundle launcher, relay restart recovery, optional mailbox attempt)

Superseded markdown: `~/fat/tenet-archive/` — do not treat as current.

---

## Containment

This file is the authority. Do not create new gates, phases, branch labels, or side runbooks. Use the queue IDs below.

Current beta path: **one matcher-only Nitro TEE + one public REACH relay + two off-TEE EC2 experts + direct client relay send**.

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
| **15** | Network beta: ≥2 humans, stable pins, run notes | **Done for automated beta proof; literal external-human run remains an ops exercise** | — | — |

**Rules (not queue IDs):**

| Rule | Text |
|------|------|
| **R1** | Security level is network-wide, never per-user |
| **R2** | Migration flips the whole network, never two live trust models |
| **R3** | No bundled default reachability-relay URLs in the repo until item **10** passed |

**Engineering shortcuts (item 9 only, not product):** in-TEE stub relay/expert in `deploy/run_matcher_live.py`, stub `por enclave send` reply, `./scripts/demo-mailbox-e2e.sh`.

**Current live path:** two-expert alpha matcher on Nitro, direct REACH relay send, `via_mailbox: false`.

**Off critical path (no queue ID):** expert groups taxonomy (`por/expert_groups.py`), Android (`android/`), ARC credentials.

---

## Verified right now (2026-06-04)

| What | Truth |
|------|--------|
| Matcher URL + pins | `config/live-enclave.json` -> **`https://5faf834eac20.aeon.site/`**, Value X `5faf834eac20adaf...`, SPKI `d5ef2ab186ec7177...`, `aw` @ `79a5ea2` |
| Nitro parent | `3.121.69.82`, instance `tenet-matcher-nitro` (`i-069a473107424b7df`, eu-central-1), SSH `~/.ssh/tenet-nitro.pem` |
| Reach relay (item 11) | UDP **4433** on `3.121.69.82`; config `config/live-reach-relay.json`; process `python3 -m por run --config config/live-reach-relay.json --node-id reach-beta-1`; return-session + stale-address cleanup + duplicate-forward replay-state preservation deployed |
| Live experts | `alpha-seed-art` -> **`h4a30b46453eb7bd`** on `35.159.21.110`; `alpha-seed-security` -> **`h0a0a24b9434a966`** on `63.185.117.35`; both REACH-only through `3.121.69.82:4433`, `POR_MAX_TOKENS=256`, `POR_STREAM_CHUNK_REPEATS=3`, `POR_STREAM_DONE_REPEATS=4`, Anthropic key loaded from remote `~/.tenet/anthropic.env` |
| TEE data | `deploy/data/beta/snapshot.json` + `mailbox.json` contain the two alpha handles above; handle + peer-address TTL **86400s**; `trusted_reachability_relays` in mailbox |
| Live EIF | `matcher-alpha-20260604-041937` on Nitro; PCR0 `8fe23accaa7c4316...`, PCR1 `4b4d5b3661b3efc1...`, PCR2 `9c6fd0b66ae65f48...` |
| Asker proof | Direct current-alpha `por ask` and `por enclave send` return real Claude text with `fallback_used: false`, `via_mailbox: false`. Current-alpha repeat/load passed `ok=20/20` at `2026-06-04T09:56:48Z` in `config/item-15-6-report.json`. Fresh EC2 asker `63.180.171.11` passed `./scripts/deploy-network-clients.sh` with `ok: true`. |
| Historical single-expert beta proof | Previous matcher `https://64a331764e39.aeon.site/` proved item 13 and item 15.6 single-expert load for `hb85f9afbccddfe5`. This is not the current live matcher and is no longer the active `config/item-15-6-report.json`. |
| Item 14 | Matcher-only entry `deploy/entry-matcher.sh`; current EIF is alpha data baked into the matcher image |
| Item 15 | Done for automated beta proof: two live experts, 20/20 current-alpha load, fresh non-expert EC2 asker, product bundle smoke. Literal external-human run remains a manual ops exercise, not a code blocker. |

Last direct product-path proof command:

```bash
env PATH=/Users/mac/.cargo/bin:$PATH python3 -m por ask \
  --join-pack config/join-pack.json \
  --prompt 'In one sentence, name one Monet painting technique.' \
  --timeout 60 --json
```

Result at `2026-06-04T09:55Z`: `ok: true`, `selected_peer_id: h4a30b46453eb7bd`, real Claude response, `fallback_used: false`, `via_mailbox: false`.

Last product asker smoke command:

```bash
./scripts/render-join-pack.sh
env PATH=/Users/mac/.cargo/bin:$PATH dist/asker-bundle/ask \
  --prompt 'In one sentence, name one Monet painting technique.' \
  --timeout 120 --json
```

Result at `2026-06-04T10:07Z`: `ok: true`, `fallback_used: false`, `selected_peer_id: h4a30b46453eb7bd`, real Claude response, `via_mailbox: false`.

**Item 15 remote asker (2026-06-04):** `config/network-clients.json` now points to fresh non-expert EC2 client **client-1** `63.180.171.11` (`i-0ffcb9c60b13f28da`). `PROMPT='In one sentence, name one Monet painting technique.' TIMEOUT=120 ./scripts/deploy-network-clients.sh` returned `ok: true`, `fallback_used: false`, `selected_peer_id: h4a30b46453eb7bd`, real Claude text.

`via_mailbox: false` is correct for the current matcher-only live path: the TEE returns the handle/peer route and the client sends directly through the REACH relay. `python3 -m por ask --via-mailbox ...` was attempted on `2026-06-04` and failed with `TimeoutError ... (no_done)`. Leave it off unless `/v1/deliver` UDP return delivery is deliberately fixed and the EIF is redeployed.

**Do not cite pytest as proof the live network works.**

## Known remaining work

| Work | Owner ID | Truth |
|------|----------|-------|
| Literal second human / independent asker | **15** | Automated independent EC2 asker passed on `63.180.171.11`. A literal external human can now run the same bundle/command; no code blocker remains. |
| Alpha repeat/load stability | **15** | Done for current alpha: `config/item-15-6-report.json` is `ok=20/20`, generated `2026-06-04T09:56:48Z`. |
| REACH restart recovery | **15** | Done for current alpha: relay was restarted and `/tmp/por-reach-records` rebuilt both expert handles by `2026-06-04T09:54Z` without manual expert restart. |
| Product packaging / outsider UX | — | Done for macOS ARM64 beta handoff: `dist/por-macos-arm64` built, `dist/asker-bundle/ask` smoke returned live `ok: true`. Linux/Windows binaries remain platform-build work, not current network proof blockers. |
| Optional TEE delivery | — | Attempted and failed with `no_done`; keep `via_mailbox: false`. This is optional unless product scope changes to require TEE `/v1/deliver` delivery. |

## Item 15 Finish List

These are the only item **15** finish-line blockers for running test nodes:

| # | Work | Done when |
|---|------|-----------|
| 15.1 | Lock current live path | **Done for current alpha:** `por enclave check` passed on `5faf...`; art/security sends passed with real provider text and no fallback |
| 15.2 | Relay/expert runtime stability | **Done for current alpha:** relay runs reviewed code with forward logs; two alpha experts are single processes; relay restart recovery, request repeats, expert replay cache, and stream redundancy are deployed. |
| 15.3 | NAT decision | **Done for current alpha:** live experts are public EC2 hosts but still use REACH-only relay routing; Mac `hb85...` is historical/not current matcher data. |
| 15.4 | TEE data alignment | **Done for current alpha:** one snapshot/mailbox pair, two handles, one shared KEM public key, signed peer-address records for both alpha experts. |
| 15.5 | Second human asker | **Done for automated second-machine proof:** fresh EC2 asker `63.180.171.11` returned live `ok: true`. Literal human run is now manual ops. |
| 15.6 | Repeat/load sanity | **Done for current alpha:** `GAP_SEC=1 TIMEOUT=120 ./scripts/run-item-15-6-load.sh` returned `ok=20/20`. |
| 15.7 | Larger answer sanity | **Done for current alpha:** three-paragraph Monet/classical-landscape prompt returned real provider text with `ok: true`, `fallback_used: false`. |
| 15.8 | Alpha/multi-expert scale-out | **Done at 2 experts:** live matcher selects `h4a30...` and `h0a0...` for different prompts. More than 2 experts remains future scale-out. |
| 15.9 | Join pack / outsider handoff | **Done for macOS beta:** `config/join-pack.json` is generated from live config; `dist/asker-bundle/ask` selects the platform binary and passed a live send. |

Do **not** make these item **15** blockers:

| Work | Status |
|------|--------|
| `via_mailbox: true` | Optional harder path only. Direct relay send is the current product beta path; `via_mailbox: false` remains expected unless live TEE `/v1/deliver` is deliberately enabled |
| Renaming `gate-b` files | Cosmetic compatibility cleanup only |
| PyInstaller / CI binary handoff | macOS ARM64 beta binary is built and smoked; CI and cross-platform artifacts are release packaging, not network proof blockers |
| `por run` product entrypoint | Product UX cleanup; `por enclave send` remains the accepted live proof command for now |
| Blanket commit of dirty tree | Not accepted. Review each dirty change before committing |

## Decision Notes (2026-06-04)

| Decision | Why |
|----------|-----|
| Kept `via_mailbox: false` as product default | Direct relay is passing; forced `--via-mailbox` failed with `no_done` and would require live EIF `/v1/deliver` UDP-return work. |
| Added client request repeats plus expert replay cache | The failing load run showed no relay `forward_hop`, so the initial client datagram was the weak point. Repeats without replay caching could duplicate provider calls; replay cache avoids that. |
| Used a fresh EC2 client as the second-machine proof | It proves the outsider path from a non-expert host. It is not literally a second human typing, but no code difference remains for a human run. |
| Left the fresh EC2 asker running | `config/network-clients.json` points at `63.180.171.11`; terminate it when the beta node campaign no longer needs it. |

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

### Item 12 — historical Mac expert laptop

```bash
./scripts/expert-onboard.sh /path/to/corpus
# Historical single-expert handle: hb85f9afbccddfe5
screen -dmS por-expert /bin/zsh -lc '
  set -a
  source /Users/mac/fry-core/.env
  set +a
  export POR_MAX_TOKENS=512
  cd /Users/mac/sphinx-tahoe
  exec python3 -m por run --config config/expert-laptop.json \
    --node-id hb85f9afbccddfe5 >>/tmp/por-expert.log 2>&1
'
```

This was the item 13 single-expert proof path. The current live matcher is alpha and does not contain `hb85f9afbccddfe5`.

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

### Item 15 — human beta (second asker)

| Client | Host | `por ask` (2026-06-04) |
|--------|------|------------------------|
| client-1 | `35.159.21.110` | `ok: true`, real Claude text, `hb85f9afbccddfe5` |
| client-2 | `63.185.117.35` | `ok: true`, real Claude text, `hb85f9afbccddfe5` |

That table is historical single-expert proof. Current alpha pins: matcher `https://5faf834eac20.aeon.site/`, SPKI `d5ef2ab186ec7177...`, `aw` @ `79a5ea2`, relay `3.121.69.82:4433`. The two EC2 hosts are now live alpha experts, not clean independent askers.

Canonical item **13** operator proof command:

```bash
python3 -m por enclave send --config config/live-enclave.json \
  --mailbox-config config/live-mailbox-client.json \
  --prompt "In one sentence, name one Monet painting technique." \
  --timeout 120 --json
```

Join-pack / `por ask` is locally smoke-proven against the current alpha matcher. The two-EC2 asker proof is historical single-expert proof; current alpha still needs an independent non-expert asker and repeat/load.

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
| `por ask` / `./scripts/package-asker-bundle.sh` | Product asker join and public bundle | Not accepted as item **15** proof until second human run succeeds |
| `./scripts/network-beta.sh` | Wrapper for `scripts/gate-b/run-network.sh` | Multi-node deploy |

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
