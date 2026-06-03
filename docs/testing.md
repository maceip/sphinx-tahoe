# Testing and running tenet

Three tiers — pick the one that matches what you are trying to prove.

## Quick reference

| Goal | Command | Needs |
|------|---------|-------|
| Default green gate | `make smoke` or `./scripts/smoke.sh` | `pip install -r requirements.txt` |
| All unit tests | `make test` | same |
| Integration / product | `./scripts/test.sh integration` / `product` | same |
| Local matcher (no TEE) | `./scripts/run-plain-matcher.sh` | Python only |
| Live attestation | `./scripts/install-aw.sh` then `./scripts/verify-live.sh` | `aw` + network + DNS → EIP |
| Product demo | `./scripts/demo-live-product.sh` | attested verify + match + plan |
| Expert plan only | `./scripts/demo-expert-plan-live.sh` | route plan via live matcher |
| Rust oblivious selector | `./scripts/build-oblivious-core.sh` | maturin + Rust toolchain |
| Live match via client | `python3 -m por enclave match --prompt "monet painting"` | `aw` + network |
| Live pytest (opt-in) | `./scripts/test.sh live` | `aw` + network |

## First-time setup

```bash
cd ~/sphinx-tahoe
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make smoke
```

## Live Nitro matcher

Trust policy is checked in at `config/live-enclave.json` (Value X + SPKI pin).
Do not hand-copy pins — update that file when redeploying a new EIF.

```bash
./scripts/install-aw.sh          # once per machine / after engine pin bump
./scripts/verify-live.sh         # aw check + healthz + client policy gate
python3 -m por enclave check     # same client gate, human output
python3 -m por enclave match --prompt "Tell me about Monet" --json
```

Override URL or config:

```bash
TENET_LIVE_ENCLAVE_URL=https://d851588d3b41.aeon.site/ ./scripts/verify-live.sh
python3 -m por enclave check --config config/live-enclave.json
```

## Local plain matcher

No attestation — exercises matcher/mailbox HTTP shape only:

```bash
./scripts/run-plain-matcher.sh
# other terminal:
curl -s http://127.0.0.1:9384/healthz
```

## Pytest markers

| Marker | Meaning |
|--------|---------|
| (default) | Unit tests; `@pytest.mark.live` excluded |
| `integration` | Multi-process / threaded |
| `product` | End-to-end product paths |
| `live` | Hits production attested matcher — opt in via `./scripts/test.sh live` |

See also `STATUS.md` and `DEPENDENCIES.md`.
