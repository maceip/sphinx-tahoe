#!/usr/bin/env bash
# AWS Nitro deploy for the matcher/mailbox enclave plane (H5).
#
# This is the sequence that was never committed as a script in runcards (the
# Nitro path is EIF + nitro-cli + parent proxy, not a single deploy.sh like the
# SNP/TDX sisters). Recovered from bountynet-genesis/v2/BUILD.md and committed
# here so it stops being tribal knowledge. See project memory `nitro_deploy_path`.
#
# What it does NOT do: generate a fresh attestation quote. That happens on the
# instance, inside the enclave, at run time. runcards' *verification* already
# works with no hardware (chain_e2e, Nitro/TDX hardware_regression fixtures); only
# fresh-quote GENERATION needs a real Nitro instance, which is what this runs on.
#
# Prereqs on the instance: a Nitro-enabled EC2 (e.g. m5.xlarge,
# --enclave-options 'Enabled=true'), docker, and the aws-nitro-enclaves-cli.
# The `bountynet` binary must be built and present in the build context as
# ./bountynet-bin (cargo build --release from the runcards/bountynet-genesis tree).
set -euo pipefail

IMAGE="${IMAGE:-matcher-enclave}"
EIF="${EIF:-matcher.eif}"
CPU_COUNT="${CPU_COUNT:-2}"
MEMORY_MIB="${MEMORY_MIB:-3500}"
PROXY_PORT="${PROXY_PORT:-443}"
ACME_FLAG="${ACME_FLAG:---acme}"   # set to "" to skip Let's Encrypt (e.g. staging)

echo "[deploy] one-time host setup (idempotent)"
sudo amazon-linux-extras install aws-nitro-enclaves-cli -y 2>/dev/null || true
sudo systemctl enable --now nitro-enclaves-allocator

echo "[deploy] build the EIF (reproducible -> PCR0/Value X)"
docker build -t "${IMAGE}:latest" -f deploy/Dockerfile.enclave .
nitro-cli build-enclave --docker-uri "${IMAGE}:latest" --output-file "${EIF}"
# Record the measurements; PCR0 is the value to approve in the trust registry
# and to set as approved_value_x in the client EnclaveTrustPolicy.
nitro-cli describe-eif --eif-path "${EIF}" | python3 -c \
  'import sys,json;m=json.load(sys.stdin)["Measurements"];print("[deploy] PCR0 =",m["PCR0"])'

echo "[deploy] run the enclave"
sudo nitro-cli run-enclave \
    --cpu-count "${CPU_COUNT}" --memory "${MEMORY_MIB}" --eif-path "${EIF}"
CID=$(nitro-cli describe-enclaves \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["EnclaveCID"])')
echo "[deploy] enclave CID = ${CID}"

echo "[deploy] start the parent vsock bridge (TLS terminates IN the enclave)"
# The parent sees only ciphertext; it provisions the cert via ACME but the TLS
# key and termination live inside the enclave (bountynet-genesis v2/src/net/vsock.rs).
bountynet proxy --cid "${CID}" --port "${PROXY_PORT}" ${ACME_FLAG}

echo "[deploy] up. verify from a client with:  runcard check --json https://<this-host>"
