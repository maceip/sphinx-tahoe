# Enclave deploy (H5)

Packaging + deploy path for running the matcher/mailbox plane inside a TEE and
letting clients attest it. Recycles the runcards / bountynet-genesis engine; no
new enclave code.

## Files

- `Dockerfile.enclave` — builds the EIF: amazonlinux:2023-minimal (reproducible
  PCR0), python3, the `por` + `sphinxmix` source, the `bountynet` attestation
  shim, and the entry/launch scripts.
- `enclave-workload.sh` — launches `por.enclave_plane_server` on loopback
  (`127.0.0.1:9384`). This is our code; it is unit-tested
  (`tests/test_enclave_plane_server.py`).
- `enclave-entry.sh` — EIF PID 1: starts the workload + bountynet attestation.
- `nitro-deploy.sh` — the AWS Nitro sequence (provision → build EIF → run-enclave
  → parent vsock proxy), recovered from `bountynet-genesis/v2/BUILD.md`. The Nitro
  path was never a committed script (it's EIF + nitro-cli + proxy, unlike the
  SNP/TDX `deploy/*.sh` sisters in runcards); this commits it.

## End-to-end path

1. Build `bountynet` (`cargo build --release` in the runcards/bountynet-genesis
   tree) → drop the binary in this build context as `./bountynet-bin`.
2. `deploy/nitro-deploy.sh` on a Nitro-enabled instance: builds the EIF, prints
   **PCR0**, runs the enclave, starts the parent `bountynet proxy` (TLS
   terminates *inside* the enclave; the parent only bridges ciphertext).
3. Approve PCR0 as the build's **Value X** in the trust registry, and set it as
   `approved_value_x` in the client `EnclaveTrustPolicy`
   (`por/enclave_attest.py`).
4. Client: `runcard check --json https://<host>` → `AttestedEnclavePlaneClient`
   verifies + pins the SPKI (H3) and only then issues matcher/mailbox calls.

## What works without hardware

runcards' **verification** runs green on a plain machine (its `chain_e2e` and the
Nitro/TDX `hardware_regression` fixtures). The client gate, SPKI pinning, oblivious
selection, and cover-handle count-hiding are all unit-tested here with no TEE.

## What genuinely needs a real instance / more work (no overclaiming)

1. **Fresh-quote generation** — only obtainable inside a live Nitro/SNP/TDX
   enclave at run time (NSM / `/dev/sev-guest` / configfs-tsm). Verification
   works locally; *generation* does not. This is the literal H5 hardware step.
2. **bountynet app-proxy (integration gap)** — bountynet-genesis v2 `cmd_enclave`
   serves the attestation JSON + EAT over the enclave vsock-TLS
   (`serve_tls_vsock`); it does **not** reverse-proxy a co-located app onto that
   same attested channel. So the matcher API is not yet reachable over attested
   TLS — the EAT/channel-binding half works, but joining the matcher's `/v1/*`
   onto it needs a bountynet enclave-proxy mode. Tracked as its own task.
3. **SNP/TDX variants** — `nitro-deploy.sh` is Nitro-specific; the SNP (Azure
   CVM) and TDX (GCP) whole-VM paths reuse runcards' `deploy/azure-cvm.sh` /
   `deploy/gcp-tdx.sh` and need no vsock bridge (see
   `../docs/enclave_plane_runcards.md`).
