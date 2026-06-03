#!/usr/bin/env bash
# Default green gate: fast unit tests + import sanity. No network, no TEE.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "[smoke] pytest (unit, excludes live)"
python3 -m pytest -q -m "not live"

echo "[smoke] import por + sphinxmix"
python3 -c "import por; import sphinxmix.OutfoxParams"
python3 -m por --help >/dev/null

echo "[smoke] ok"
