#!/usr/bin/env bash
# Expert onboarding: opaque handle + enclave data build steps (item 12).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${BETA_SECRETS:-$ROOT/config/beta-secrets.env}"
CORPUS="${1:-}"

if [[ -z "$CORPUS" || ! -d "$CORPUS" ]]; then
  echo "usage: $0 <expert-corpus-directory>" >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "run ./scripts/init-beta-secrets.sh first" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

HANDLE_TOKEN="$(
  python3 -c "
from por.handles import OpaqueHandleIssuer
issuer = OpaqueHandleIssuer(bytes.fromhex('${HANDLE_SECRET_HEX}'))
print(issuer.issue(peer_id='expert', manifest_digest='0'*64).token)
"
)"

echo "[expert-onboard] opaque handle token: $HANDLE_TOKEN"
echo "[expert-onboard] steps:"
echo "  1. ./scripts/render-beta-config.sh  (after REACH_RELAY_HOST is set)"
echo "  2. Replace REPLACE_WITH_OPAQUE_HANDLE in config/expert-laptop.json with: $HANDLE_TOKEN"
echo "  3. Start expert:"
echo "       export ANTHROPIC_API_KEY=..."
echo "       python3 -m por run --config config/expert-laptop.json --node-id $HANDLE_TOKEN"
echo "  4. Export signed peer_address record to peer-address.json (from expert logs or tooling)"
echo "  5. Build TEE data:"
echo "       python3 scripts/build-beta-enclave-data.py \\"
echo "         --corpus $CORPUS \\"
echo "         --peer-id expert \\"
echo "         --handle-secret-hex $HANDLE_SECRET_HEX \\"
echo "         --routing-kem-pk-hex $EXPERT_KEM_PK_HEX \\"
echo "         --peer-address-json peer-address.json"
echo "  6. Redeploy Nitro EIF with deploy/data/beta/* and update live-enclave pins if needed"
