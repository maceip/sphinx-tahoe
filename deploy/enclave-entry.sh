#!/bin/sh
# EIF entry point (H5). Starts the matcher workload on loopback and the bountynet
# attestation server, then waits.
#
# HONEST STATUS: bountynet serves the EAT/attestation over the enclave vsock-TLS
# (the channel-binding half works end to end). It does NOT yet reverse-proxy the
# matcher's HTTP API onto that same attested channel — that is the tracked
# `bountynet app-proxy` integration item. So today this brings up both processes;
# the matcher API is reachable on loopback inside the enclave, and a client can
# `runcard check` the attested endpoint, but the two are not yet joined.
set -eu

# 1) matcher/mailbox workload on loopback (our code; unit-tested)
/usr/local/bin/enclave-workload.sh &
WORKLOAD_PID=$!

# 2) bountynet: attest the image + serve attestation/EAT over vsock-TLS.
#    `enclave /app --cmd true` ratchets + measures /app (no build for Python),
#    collects the quote, and serves. Parent runs `bountynet proxy --cid <cid>`.
bountynet enclave /app --cmd true &
BOUNTYNET_PID=$!

# Exit if either dies; surface which one.
wait -n "${WORKLOAD_PID}" "${BOUNTYNET_PID}"
echo "[enclave-entry] a process exited; shutting down" >&2
kill "${WORKLOAD_PID}" "${BOUNTYNET_PID}" 2>/dev/null || true
exit 1
