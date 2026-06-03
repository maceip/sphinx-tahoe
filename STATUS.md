# tenet / sphinx-tahoe — status

**Updated:** 2026-06-04 (autonomous battle-plan pass)  
**Baseline:** `make smoke` → **257 passed, 2 skipped**

## Battle plan progress

| Priority | Item | Status |
|----------|------|--------|
| — | Tiered test scripts + `config/live-enclave.json` | **Done** |
| — | Client policy + `por enclave check/match` | **Done** |
| P2 | Elastic IP + DNS | **Done** — `3.121.69.82` |
| P1 | PyO3 `oblivious-core` | **Done (dev)** / **Done (EIF recipe)** — multi-stage `Dockerfile.matcher-real` |
| P1b | Redeploy EIF with Rust selector on Nitro | **Pending** — changes Value X; run when ready |
| P4 | Expert routing e2e | **Partial** — `por enclave plan` + demos; mixnet delivery still open |
| OUT | Azure SNP, mpTLS, per-user tiers | Deferred |

## Live endpoint

| Item | Value |
|------|-------|
| **URL** | https://d851588d3b41.aeon.site/ |
| **Elastic IP** | `3.121.69.82` |
| **Engine** | attested-workload @ `79a5ea2328f2b30192e57b53913355dcd5e0201e` |
| **Value X** | `d851588d3b413cbf7513d9d5fa93d466b42ad1603e1c7fdfd408cfd635a7cf6882412ce99c8fbb3aeac197c3e6c5f361` |
| **tls_spki_hash** | `b880512378622821deebd4cb395a82eae271069acd491b805940145c97d1eab1` |

Public DNS verified on 8.8.8.8 → `3.121.69.82`. Local resolver cache may lag; `verify-live.sh` uses `curl --resolve` for healthz.

## Runnable demos (in order)

```bash
make smoke
./scripts/install-aw.sh && ./scripts/verify-live.sh
python3 -m por enclave match --prompt "monet painting"
python3 -m por enclave plan --prompt "monet painting"    # expert-mode plan
./scripts/demo-live-product.sh                           # all of the above
./scripts/demo-expert-plan-live.sh                       # plan only
```

## Next up

1. **Redeploy EIF** on Nitro with Rust oblivious selector (`assemble-matcher-eif.sh` → docker → nitro-cli); refresh pins in `config/live-enclave.json`.
2. **Mixnet e2e** — `run_client_once` with envelope delivery to expert via attested mailbox path.
3. **Home-router / persistent connections** (product rename prep).

## One command truth

```bash
make smoke
./scripts/verify-live.sh
./scripts/demo-live-product.sh
```

Full guide: `docs/testing.md`
