# External dependencies (pinned)

## attested-workload (TEE engine)

**Repo:** https://github.com/maceip/attested-workload  
**Pin:** `e039216` (initial release — TEE + attested TLS + Nitro app-proxy)

Build the enclave shim for EIF images:

```bash
ATTESTED_WORKLOAD_SHA=e039216 ./deploy/build-bountynet-bin.sh
```

Client verification uses the same repo:

```bash
cargo install --git https://github.com/maceip/attested-workload --rev e039216 --bin aw
# or: aw check --json https://<matcher-host>/
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
