# tenet / sphinx-tahoe — status

**Updated:** 2026-06-04 (P1b + live P4 closed)  
**Baseline:** `make smoke` → **257 passed, 2 skipped**

## Battle plan progress

| Priority | Item | Status |
|----------|------|--------|
| — | Tiered test scripts + `config/live-enclave.json` | **Done** |
| — | Client policy + `por enclave check/match` | **Done** |
| P2 | Elastic IP + DNS | **Done** — `3.121.69.82` |
| P1 | PyO3 `oblivious-core` | **Done** — dev + EIF (Rust selector in enclave) |
| P1b | Redeploy EIF with Rust selector on Nitro | **Done** |
| P4 | Expert routing e2e (live) | **Done** — `por enclave send` + `./scripts/demo-live-mailbox-e2e.sh` |
| OUT | Azure SNP, mpTLS, per-user tiers | Deferred |

## Live endpoint

| Item | Value |
|------|-------|
| **URL** | https://ba637abc5bc8.aeon.site/ |
| **Elastic IP** | `3.121.69.82` |
| **Engine** | attested-workload @ `79a5ea2328f2b30192e57b53913355dcd5e0201e` |
| **Value X** | `ba637abc5bc82cef1fd41e20255560a40b8f5b0ee4a33d9bad8a5e128b52238a8392cddf6e0e5cc8dd764f5b4b697d5b` |
| **tls_spki_hash** | `5e26392e52789a17798b4fb54b1bbf0714d7c233dadc8dc580b35c76a98c28e8` |
| **Workload** | `run_matcher_live.py` — matcher + in-enclave relay/expert mailbox fleet |

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
