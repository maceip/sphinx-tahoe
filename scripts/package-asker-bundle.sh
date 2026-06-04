#!/usr/bin/env bash
# Zip public asker files for a second human (no secrets).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/render-join-pack.sh"
OUT="$ROOT/dist/asker-bundle"
rm -rf "$OUT"
mkdir -p "$OUT"
cp "$ROOT/config/join-pack.json" "$OUT/"
cp "$ROOT/config/live-mailbox-client.json" "$OUT/"
(
  cd "$ROOT/dist"
  rm -f asker-bundle.zip
  zip -r asker-bundle.zip asker-bundle
)
echo "[asker-bundle] dist/asker-bundle.zip"
echo "Ask: por ask --join-pack asker-bundle/join-pack.json --prompt '...'"
