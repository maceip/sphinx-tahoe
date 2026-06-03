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
aw check --json https://ba637abc5bc8.aeon.site/
```

### Live deployment pins (tenet matcher, 2026-06-04 — live mailbox fleet)

Use in `EnclaveTrustPolicy` after `aw check --json` (or load `config/live-enclave.json`):

```bash
python3 -m por enclave check
python3 -m por enclave match --prompt "Tell me about Monet"
python3 -m por enclave send --prompt "Tell me about Monet"
```

```text
value_x:       ba637abc5bc82cef1fd41e20255560a40b8f5b0ee4a33d9bad8a5e128b52238a8392cddf6e0e5cc8dd764f5b4b697d5b
tls_spki_hash: 5e26392e52789a17798b4fb54b1bbf0714d7c233dadc8dc580b35c76a98c28e8
platform:      nitro
domain:        ba637abc5bc8.aeon.site   # first 12 hex chars of Value X + base domain
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
