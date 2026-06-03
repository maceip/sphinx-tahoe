# tenet / sphinx-tahoe — status

**Updated:** 2026-06-04  
**Baseline:** `make smoke` → **257 passed, 2 skipped** (optional crypto backends)

## Battle plan progress

| Priority | Item | Status |
|----------|------|--------|
| — | Tiered test scripts + `config/live-enclave.json` | **Done** (`c8ca57e`) |
| — | Client policy + `por enclave check/match` | **Done** |
| P2 | Elastic IP for Nitro parent | **Done** — `3.121.69.82` (`eipalloc-00ee832114956db7e`) |
| P2b | DNS → Elastic IP | **Done** — `d851588d3b41.aeon.site` / `aeon.site` → `3.121.69.82` (Google/Cloudflare DNS) |
| P1 | PyO3 `oblivious-core` in matcher | **Partial** — dev wired; EIF Docker image still uses Python selector |
| P4 | Expert routing e2e (mixnet → live matcher) | **Partial** — `scripts/demo-live-product.sh` (attested match demo) |
| OUT | Azure SNP, mpTLS, per-user tiers | Deferred |

## Milestone: live attested matcher on AWS Nitro

The full H1–H5 trust stack is validated on real hardware with production TLS:

| Item | Value |
|------|-------|
| **Live endpoint** | https://d851588d3b41.aeon.site/ |
| **Instance** | `tenet-matcher-nitro` (`i-069a473107424b7df`, m5.xlarge, eu-central-1) |
| **Elastic IP** | `3.121.69.82` (`eipalloc-00ee832114956db7e`) — stable across stop/start |
| **Previous IP** | `63.178.62.239` (released when EIP associated) |
| **Engine pin** | [attested-workload](https://github.com/maceip/attested-workload) @ `79a5ea2328f2b30192e57b53913355dcd5e0201e` |
| **Value X** | `d851588d3b413cbf7513d9d5fa93d466b42ad1603e1c7fdfd408cfd635a7cf6882412ce99c8fbb3aeac197c3e6c5f361` |
| **tls_spki_hash** (post-ACME) | `b880512378622821deebd4cb395a82eae271069acd491b805940145c97d1eab1` |

**Verified 2026-06-04 (public DNS):**

```bash
dig +short d851588d3b41.aeon.site @8.8.8.8   # 3.121.69.82
curl --resolve d851588d3b41.aeon.site:443:3.121.69.82 https://d851588d3b41.aeon.site/healthz
./scripts/verify-live.sh   # after local DNS catches up (or use --resolve above)
```

Let's Encrypt cert on `d851588d3b41.aeon.site` still valid; `bountynet proxy --acme` running on instance.

Details: `deploy/HARDWARE_VALIDATION_2026-06-03.md`, `docs/enclave_plane_attested_workload.md`.

## Engine consolidation (done)

| Before | After |
|--------|-------|
| `runcards` + `bountynet-genesis` | Single pin: **attested-workload** |
| `runcard check --json` | `aw check --json` |
| Unpinned deploy | `DEPENDENCIES.md` + CI gate |

## Done (product + trust)

- Outfox mixnet, wire daemon, mixnet tests
- Matcher/mailbox + oblivious selection (H4) + cover handles
- Client attestation gate (H1–H2) → `aw check --json`
- SPKI-pinned transport (H3)
- Nitro EIF packaging + deploy scripts (H5)
- Let's Encrypt + post-ACME EAT rebind (`79a5ea2`)
- Tiered testing (`make smoke`, `verify-live`, `docs/testing.md`)
- Live client config (`config/live-enclave.json`, `por enclave`)
- Elastic IP + `deploy/associate-elastic-ip.sh`
- PyO3 oblivious-core (local/dev via `./scripts/build-oblivious-core.sh`)

## Next up

1. ~~**DNS**~~ — done (`3.121.69.82` on public resolvers).
2. **EIF** — bake `oblivious_core` into `Dockerfile.matcher-real` for in-TEE Rust selector.
3. **Mixnet e2e** — client prompt over Outfox path to attested `/v1/match` (full product demo).

## One command truth

```bash
make smoke                                    # unit gate
./scripts/run-plain-matcher.sh                # local matcher
./scripts/install-aw.sh && ./scripts/verify-live.sh   # live (after DNS)
./scripts/demo-live-product.sh                # attested product demo
./scripts/build-oblivious-core.sh             # optional Rust selector
```

Full guide: `docs/testing.md`

## Doc map

1. `docs/matcher_threat_model.md` — architecture of record
2. `STATUS.md` (this file) — live vs planned
3. `docs/testing.md` — how to run each tier
4. `DEPENDENCIES.md` — engine pin + live client pins
5. `deploy/README.md` — Nitro bring-up
