# tenet / sphinx-tahoe — status

**Updated:** 2026-06-03  
**Baseline:** `pytest -q` → **250 passed, 2 skipped** (optional crypto backends)

## Milestone: live attested matcher on AWS Nitro

The full H1–H5 trust stack is **validated on real hardware** with production TLS:

| Item | Value |
|------|-------|
| **Live endpoint** | https://d851588d3b41.aeon.site/ |
| **Instance** | `tenet-matcher-nitro` (`i-069a473107424b7df`, m5.xlarge, eu-central-1) |
| **Public IP** | `63.178.62.239` (allocate Elastic IP before stop/start) |
| **Engine pin** | [attested-workload](https://github.com/maceip/attested-workload) @ `79a5ea2328f2b30192e57b53913355dcd5e0201e` |
| **Value X** | `d851588d3b413cbf7513d9d5fa93d466b42ad1603e1c7fdfd408cfd635a7cf6882412ce99c8fbb3aeac197c3e6c5f361` |
| **tls_spki_hash** (post-ACME) | `b880512378622821deebd4cb395a82eae271069acd491b805940145c97d1eab1` |
| **EIF PCR0** | `e420380c20ab4b6b1bea5ca98a0627607f0f6075bc376296a964299f8b59ae3fd953af4ea6b14c6d0a1ee4507dc497ff` |

**Verify from any machine:**

```bash
aw check --json https://d851588d3b41.aeon.site/
curl -s https://d851588d3b41.aeon.site/healthz
```

Details: `deploy/HARDWARE_VALIDATION_2026-06-03.md`, `docs/enclave_plane_attested_workload.md`.

## Engine consolidation (done)

| Before | After |
|--------|-------|
| `runcards` verifier + `bountynet-genesis` enclave shim | Single pin: **attested-workload** |
| `runcard check --json` | `aw check --json` (schema unchanged) |
| Unpinned deploy binaries | `DEPENDENCIES.md` + CI gate |

Do **not** mix legacy repos on the live path.

## Done (product + trust)

- Outfox mixnet core, wire daemon, mixnet tests
- Matcher/mailbox stand-in + oblivious selection (H4) + cover handles
- Client attestation gate (H1–H2) → `aw check --json`
- SPKI-pinned transport (H3)
- Nitro EIF packaging + deploy scripts (H5)
- App-proxy `/v1/*` → loopback matcher (in attested-workload)
- Let's Encrypt via TLS-ALPN-01 + post-ACME EAT rebind (`79a5ea2`)
- Expert groups, Android client + CI

## Open (post-milestone)

| Priority | Item |
|----------|------|
| P1 | Wire `oblivious-core` into live matcher via PyO3 (Rust exists; Python selector still used in enclave) |
| P2 | Elastic IP for Nitro parent (current IP is ephemeral) |
| P3 | Client `EnclaveTrustPolicy.approved_value_x` + pinned `tls_spki_hash` in tenet config docs |
| P4 | Azure SNP path (blocked by paravisor — documented defect) |
| OUT | mpTLS / TLSNotary / per-user security tiers until post-ship |

## One command truth

```bash
cd ~/sphinx-tahoe && pytest -q          # default green gate
cd ~/oblivious-core && cargo test       # Rust oblivious core (not wired to matcher yet)
aw check --json https://d851588d3b41.aeon.site/   # live attestation (needs `aw` from pinned SHA)
```

## Doc map (read order)

1. `docs/matcher_threat_model.md` — architecture of record
2. `STATUS.md` (this file) — what's live vs planned
3. `docs/enclave_plane_attested_workload.md` — TEE integration
4. `DEPENDENCIES.md` — external pins
5. `deploy/README.md` — Nitro bring-up
