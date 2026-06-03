#!/usr/bin/env bash
# AWS Nitro deploy for the tenet matcher enclave (H5).
#
# Prereqs: Nitro-enabled EC2, docker, aws-nitro-enclaves-cli, build context with
# bountynet-bin (see assemble-matcher-eif.sh or build-bountynet-bin.sh).
#
# Engine: https://github.com/maceip/attested-workload (pin in DEPENDENCIES.md)
set -euo pipefail

IMAGE="${IMAGE:-matcher-real}"
EIF="${EIF:-matcher.eif}"
DOCKERFILE="${DOCKERFILE:-Dockerfile.matcher-real}"
CPU_COUNT="${CPU_COUNT:-2}"
MEMORY_MIB="${MEMORY_MIB:-3500}"
PROXY_PORT="${PROXY_PORT:-443}"
ACME_FLAG="${ACME_FLAG:---acme}"

echo "[deploy] one-time host setup (idempotent)"
sudo amazon-linux-extras install aws-nitro-enclaves-cli -y 2>/dev/null || true
sudo systemctl enable --now nitro-enclaves-allocator

echo "[deploy] build the EIF (reproducible -> PCR0 / Value X)"
docker build -t "${IMAGE}:latest" -f "${DOCKERFILE}" .
nitro-cli build-enclave --docker-uri "${IMAGE}:latest" --output-file "${EIF}"
nitro-cli describe-eif --eif-path "${EIF}" | python3 -c \
  'import sys,json;m=json.load(sys.stdin)["Measurements"];print("[deploy] PCR0 =",m["PCR0"])'

echo "[deploy] run the enclave"
sudo nitro-cli run-enclave \
    --cpu-count "${CPU_COUNT}" --memory "${MEMORY_MIB}" --eif-path "${EIF}"
CID=$(nitro-cli describe-enclaves \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["EnclaveCID"])')
echo "[deploy] enclave CID = ${CID}"

echo "[deploy] parent vsock bridge (TLS terminates IN the enclave; app-proxy on :8080)"
bountynet proxy --cid "${CID}" --port "${PROXY_PORT}" ${ACME_FLAG}

echo "[deploy] up. verify:  aw check --json https://<this-host>/"
