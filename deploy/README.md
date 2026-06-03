# Enclave deploy (H5)

Packaging + deploy for running the matcher/mailbox plane inside a TEE with
client attestation. The TEE engine lives in
**[attested-workload](https://github.com/maceip/attested-workload)** (pinned in
`DEPENDENCIES.md`).

## Build the enclave shim

```bash
ATTESTED_WORKLOAD_SHA=e039216 ./deploy/build-bountynet-bin.sh
```

Produces `./bountynet-bin` (same as `aw` / `bountynet` from attested-workload).

## Files

| File | Role |
|------|------|
| `build-bountynet-bin.sh` | Build `bountynet-bin` from pinned attested-workload |
| `assemble-matcher-eif.sh` | Stage build context for the real-matcher EIF |
| `Dockerfile.matcher-real` | EIF with `por.PlainMatcher` + app-proxy on `:8080` |
| `entry-matcher.sh` | PID 1: matcher on loopback, `bountynet enclave` with app-proxy |
| `run_matcher.py` | Loopback HTTP server the app-proxy fronts |
| `nitro-deploy.sh` | Nitro: build EIF → run enclave → parent proxy |

Legacy `Dockerfile.enclave` + `enclave_plane_server` remain for the older
stand-in plane; new Nitro work should use `Dockerfile.matcher-real`.

## End-to-end (Nitro)

```bash
# On your build machine
ATTESTED_WORKLOAD_SHA=e039216 ./deploy/assemble-matcher-eif.sh
# Copy deploy/eif-build/ to a Nitro-enabled instance, then:
cd eif-build && ../nitro-deploy.sh   # or docker build + nitro-cli manually
```

Inside the enclave:

1. Matcher listens on `127.0.0.1:8080`
2. `bountynet enclave /app` measures the workload tree, serves attested TLS over vsock
3. App-proxy forwards `/v1/*` and `/healthz` to the matcher (SSE streaming supported)

On the parent: `bountynet proxy --cid <cid>` bridges TCP:443 → vsock (TLS terminates
**inside** the enclave).

## Client verification

```bash
aw check --json https://<host>/
```

Then `AttestedEnclavePlaneClient` in `por/enclave_attest.py` (default verifier:
`SubprocessAttestedWorkloadVerifier` → `aw check --json`).

Set `approved_value_x` in `EnclaveTrustPolicy` to the Value X from deploy (PCR0 /
`aw check` output).

## What works without hardware

attested-workload verification (`cargo test` in that repo) and all sphinx-tahoe
client gate / SPKI pinning / oblivious-selection tests run on a plain machine.

## What needs a real instance

**Fresh quote generation** only — inside live Nitro/SNP/TDX at run time. Verification
does not require hardware.

## SNP / TDX

Whole-VM paths use attested-workload `deploy/azure-cvm.sh` and `deploy/gcp-tdx.sh`
(no vsock bridge). See `docs/enclave_plane_attested_workload.md`.
