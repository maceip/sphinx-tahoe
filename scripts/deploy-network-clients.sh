#!/usr/bin/env bash
# Deploy asker bundle to network clients and run por ask (item 15 proof).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLIENTS_CFG="${TENET_NETWORK_CLIENTS:-$ROOT/config/network-clients.json}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/tenet-nitro.pem}"
PROMPT="${PROMPT:-In one sentence, name one Monet painting technique.}"
TIMEOUT="${TIMEOUT:-120}"

cd "$ROOT"
[[ -f "$CLIENTS_CFG" ]] || {
  echo "missing $CLIENTS_CFG - run ./scripts/provision-network-clients.sh" >&2
  exit 1
}

export PATH="${HOME}/.cargo/bin:${PATH:-}"
if ! command -v aw >/dev/null 2>&1; then
  echo "[deploy-clients] installing aw locally (for reference)..." >&2
  "$ROOT/scripts/install-aw.sh" || true
fi

"$ROOT/scripts/package-asker-bundle.sh" >/dev/null

export ROOT
python3 <<'PY'
import json, os, subprocess, sys
from pathlib import Path

root = Path(os.environ["ROOT"])
cfg = json.loads((root / "config/network-clients.json").read_text())
key = Path(cfg["clients"][0]["ssh_key"]).expanduser()
bundle = root / "dist/asker-bundle.zip"
prompt = __import__("os").environ.get("PROMPT", "In one sentence, name one Monet painting technique.")
timeout = __import__("os").environ.get("TIMEOUT", "120")
results = []

remote_setup = r'''
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv curl ca-certificates unzip \
  build-essential pkg-config libssl-dev
if ! command -v aw >/dev/null; then
  if ! command -v cargo >/dev/null; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    . "$HOME/.cargo/env"
  fi
  . "$HOME/.cargo/env" 2>/dev/null || true
  cargo install --git https://github.com/maceip/attested-workload \
    --rev 79a5ea2328f2b30192e57b53913355dcd5e0201e --bin aw --locked 2>/dev/null \
    || cargo install --git https://github.com/maceip/attested-workload \
    --rev 79a5ea2328f2b30192e57b53913355dcd5e0201e --bin aw --force
fi
mkdir -p ~/sphinx-tahoe ~/asker-bundle
'''

for index, client in enumerate(cfg["clients"]):
    host = client["host"]
    cid = client["client_id"]
    print(f"[deploy-clients] === {cid} @ {host} ===", flush=True)
    subprocess.run(
        ["rsync", "-az", "-e", f"ssh -i {key} -o StrictHostKeyChecking=accept-new",
         "--exclude", ".git", "--exclude", "build", "--exclude", "dist", "--exclude", "deploy/eif-build",
         str(root) + "/", f"ubuntu@{host}:~/sphinx-tahoe/"],
        check=True,
    )
    subprocess.run(
        ["scp", "-i", str(key), "-o", "StrictHostKeyChecking=accept-new",
         str(bundle), f"ubuntu@{host}:~/asker-bundle.zip"],
        check=True,
    )
    cmd = f"""
{remote_setup}
cd ~/sphinx-tahoe
python3 -m pip install --user -q -e . 2>/dev/null || python3 -m pip install --user -q .
cd ~
rm -rf asker-bundle && unzip -o -q asker-bundle.zip
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
cd ~/asker-bundle
python3 -m por ask --join-pack join-pack.json --prompt {json.dumps(prompt)} --timeout {timeout} --json
"""
    proc = subprocess.run(
        ["ssh", "-i", str(key), "-o", "StrictHostKeyChecking=accept-new",
         f"ubuntu@{host}", "bash", "-s"],
        input=cmd,
        text=True,
        capture_output=True,
    )
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    ok = (
        proc.returncode == 0
        and '"ok": true' in proc.stdout
        and '"response_text": ""' not in proc.stdout
        and '"response_text": "' in proc.stdout
    )
    results.append((cid, host, ok, proc.returncode))
    if index < len(cfg["clients"]) - 1:
        import time
        time.sleep(3)
    if not ok:
        print(f"[deploy-clients] FAIL {cid}", file=sys.stderr)

print("[deploy-clients] summary:")
for cid, host, ok, rc in results:
    print(f"  {cid} {host}: ok={ok} rc={rc}")
if not all(r[2] for r in results):
    sys.exit(1)
print("[deploy-clients] item 15 second-human path OK on all clients")
PY
