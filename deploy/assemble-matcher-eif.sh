#!/usr/bin/env bash
# Stage a Docker build context for the real-matcher Nitro EIF.
#
# Output: deploy/eif-build/  (docker build -f Dockerfile.matcher-real .)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/deploy/eif-build"
SHA="${ATTESTED_WORKLOAD_SHA:-e039216}"

rm -rf "$OUT"
mkdir -p "$OUT/app"

echo "[assemble] bountynet-bin from attested-workload @ $SHA"
ATTESTED_WORKLOAD_SHA="$SHA" "$ROOT/deploy/build-bountynet-bin.sh" "$OUT/bountynet-bin"

echo "[assemble] matcher workload"
cp -R "$ROOT/por" "$OUT/app/"
cp "$ROOT/deploy/run_matcher.py" "$OUT/app/"
cp "$ROOT/deploy/entry-matcher.sh" "$OUT/"
cp "$ROOT/deploy/Dockerfile.matcher-real" "$OUT/Dockerfile"

echo "[assemble] ready: cd deploy/eif-build && docker build -t matcher-real ."
echo "[assemble] attested-workload pin: $SHA"
