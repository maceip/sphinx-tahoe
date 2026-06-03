# External dependencies (pinned)

## attested-workload (TEE engine)

**Repo:** https://github.com/maceip/attested-workload  
**Pin:** `79a5ea2328f2b30192e57b53913355dcd5e0201e` (short: `79a5ea2`)  
**Tag:** `v0.1.0` @ `e039216` (initial); live Nitro validation uses `79a5ea2` (post-ACME EAT rebind)

Build the enclave shim for EIF images:

```bash
ATTESTED_WORKLOAD_SHA=79a5ea2328f2b30192e57b53913355dcd5e0201e ./deploy/build-bountynet-bin.sh
```

Client verification uses the same repo and SHA:

```bash
cargo install --git https://github.com/maceip/attested-workload --rev 79a5ea2 --bin aw
aw check --json https://d851588d3b41.aeon.site/
```

### Live deployment pins (tenet matcher, 2026-06-03)

Use in `EnclaveTrustPolicy` after `aw check --json` (or load `config/live-enclave.json`):

```bash
python3 -m por enclave check
python3 -m por enclave match --prompt "Tell me about Monet"
```

```text
value_x:       d851588d3b413cbf7513d9d5fa93d466b42ad1603e1c7fdfd408cfd635a7cf6882412ce99c8fbb3aeac197c3e6c5f361
tls_spki_hash: b880512378622821deebd4cb395a82eae271069acd491b805940145c97d1eab1
platform:      nitro
domain:        d851588d3b41.aeon.site   # first 12 hex chars of Value X + base domain
```

### What moved here

| Before | After |
|--------|-------|
| `runcards` — quote verifier, `runcard check --json` | `aw check --json` (schema `runcard.check.v1` unchanged) |
| `bountynet-genesis/v2` — Nitro vsock + app-proxy | `src/net/vsock.rs` in attested-workload |
| Split build contexts | Single `bountynet-bin` from attested-workload |

### Do not mix

Do not pair a verifier from `runcards` with an enclave shim from `bountynet-genesis`.
Pin one `attested-workload` SHA for both sides.

## Outfox mixnet

In-tree (`sphinxmix/`). Not part of attested-workload.
