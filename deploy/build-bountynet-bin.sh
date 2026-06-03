#!/usr/bin/env bash
# Build bountynet-bin from attested-workload for sphinx-tahoe EIF images.
#
# Usage:
#   ATTESTED_WORKLOAD_REPO=~/attested-workload ATTESTED_WORKLOAD_SHA=<git-sha> \
#     ./deploy/build-bountynet-bin.sh
#
# Writes ./bountynet-bin in the current directory (typically sphinx-tahoe root).
set -euo pipefail

REPO="${ATTESTED_WORKLOAD_REPO:-$HOME/attested-workload}"
SHA="${ATTESTED_WORKLOAD_SHA:-}"
OUT="${1:-./bountynet-bin}"
case "$OUT" in
  /*) ;;
  *) OUT="$(pwd)/$OUT" ;;
esac
mkdir -p "$(dirname "$OUT")"

if [[ ! -d "$REPO/.git" ]]; then
  echo "[build-bountynet-bin] clone attested-workload into $REPO first" >&2
  exit 1
fi

pushd "$REPO" >/dev/null
if [[ -n "$SHA" ]]; then
  git fetch --quiet origin 2>/dev/null || true
  git checkout "$SHA"
fi
echo "[build-bountynet-bin] attested-workload $(git rev-parse --short HEAD)"
cargo build --release --bin bountynet
cp target/release/bountynet "$OUT"
popd >/dev/null
echo "[build-bountynet-bin] wrote $OUT"
