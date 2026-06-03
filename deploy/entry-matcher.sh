#!/bin/sh
# EIF entry: start the real matcher on loopback :8080, then bountynet (attestation
# + app-proxy over vsock-TLS). bountynet's serve_tls_vsock forwards /v1/* here.
ip link set lo up 2>/dev/null || true
ip addr add 127.0.0.1/8 dev lo 2>/dev/null || true
cd /app
PYTHONPATH=/app MATCHER_HOST=127.0.0.1 MATCHER_PORT=8080 python3.11 run_matcher.py &
exec bountynet enclave /app --cmd true
