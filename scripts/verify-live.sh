#!/usr/bin/env bash
# Verify the live attested matcher (aw check + healthz).
#
# Usage:
#   ./scripts/install-aw.sh          # once
#   ./scripts/verify-live.sh
#   ./scripts/verify-live.sh https://other-host/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=pinned-sha.sh
. "$ROOT/scripts/pinned-sha.sh"

URL="${1:-$LIVE_ENCLAVE_URL}"
AW_BIN="${AW_BIN:-aw}"

if ! command -v "$AW_BIN" >/dev/null 2>&1; then
  echo "[verify-live] $AW_BIN not found — run: ./scripts/install-aw.sh" >&2
  exit 1
fi

echo "[verify-live] attestation (pinned engine ${ATTESTED_WORKLOAD_SHORT})"
AW_BIN="$AW_BIN" "$ROOT/deploy/verify-enclave.sh" "$URL"

URL="${URL%/}"
echo "[verify-live] healthz"
if command -v curl >/dev/null 2>&1; then
  curl -fsS "$URL/healthz"
  echo
else
  python3 - <<PY
import json, urllib.request
print(json.load(urllib.request.urlopen("${URL}/healthz", timeout=15)))
PY
fi

echo "[verify-live] client policy check (config + AttestedEnclavePlaneClient)"
python3 -m por enclave check --config "$ROOT/$LIVE_ENCLAVE_CONFIG"

echo "[verify-live] ok"
