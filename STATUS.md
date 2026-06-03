# tenet / sphinx-tahoe — status

**Updated:** 2026-06-04 (P1b + live P4)  
**Baseline:** `make smoke` → **257 passed, 2 skipped**

## Battle plan progress

| Priority | Item | Status |
|----------|------|--------|
| — | Tiered test scripts + `config/live-enclave.json` | **Done** |
| — | Client policy + `por enclave check/match` | **Done** |
| P2 | Elastic IP + DNS | **Done** — `3.121.69.82` |
| P1 | PyO3 `oblivious-core` | **Done** — dev + EIF (Rust selector in enclave) |
| P1b | Redeploy EIF with Rust selector on Nitro | **Done** — see live endpoint pins below |
| P4 | Expert routing e2e (live) | **Done** — `por enclave send` + `./scripts/demo-live-mailbox-e2e.sh` |
| OUT | Azure SNP, mpTLS, per-user tiers | Deferred |

## Live endpoint

| Item | Value |
|------|------|
| **URL** | _updated after redeploy — see `config/live-enclave.json`_ |
| **Elastic IP** | `3.121.69.82` |
| **Engine** | attested-workload @ `79a5ea2328f2b30192e57b53913355dcd5e0201e` |
| **Workload** | `run_matcher_live.py` — matcher + in-enclave relay/expert mailbox fleet |
| **Pins** | `config/live-enclave.json` + `config/live-mailbox-client.json` |

Public DNS: `{value_x_prefix}.aeon.site` → `3.121.69.82` (wildcard `*.aeon.site` recommended).

## Runnable demos (in order)

```bash
make smoke
./scripts/install-aw.sh && ./scripts/verify-live.sh
python3 -m por enclave match --prompt "monet painting"
python3 -m por enclave plan --prompt "monet painting"
python3 -m por enclave send --prompt "monet painting"       # live P4 mailbox path
./scripts/demo-live-mailbox-e2e.sh
./scripts/demo-live-product.sh
./scripts/demo-mailbox-e2e.sh                            # local harness only
```

## One command truth

```bash
make smoke
./scripts/verify-live.sh
./scripts/demo-live-mailbox-e2e.sh
```

Full guide: `docs/testing.md`
