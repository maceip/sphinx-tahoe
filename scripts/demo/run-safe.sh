#!/usr/bin/env bash
# Operationalized demo fallback — single machine, no join-pack / live matcher / keys required.
#
# Cascade (MODE=auto, default):
#   1. present.py     — stage screencast (needs ANTHROPIC_API_KEY; narrated x402 + real mixnet)
#   2. berlin_pick.py — real mixnet on loopback (Claude if key, else transport-only)
#   3. replay         — cat ~/tenet/demo-recording.txt (hard fallback)
#
# Other modes: present | berlin | replay | sim-host | sim-clients
#
# Examples:
#   ./scripts/demo/run-safe.sh
#   MODE=berlin ./scripts/demo/run-safe.sh
#   MODE=replay ./scripts/demo/run-safe.sh
#   MODE=present --fast ./scripts/demo/run-safe.sh
#   MODE=sim-host ./scripts/demo/run-safe.sh   # host-process sim mesh, then berlin_pick
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

MODE="${MODE:-auto}"
RECORD="${RECORD:-0}"
PROMPT="${PROMPT:-Get me an Airbnb in Berlin — which neighbourhood should I stay in?}"
RECORDING="${TENET_DEMO_RECORDING:-$ROOT/demo-recording.txt}"
FRY_ENV="${FRY_ENV:-$HOME/fry-core/.env}"
SIM_SCENARIO="${SIM_SCENARIO:-sim/scenarios/all-local-docker-small.yaml}"
# shellcheck disable=SC2034
EXTRA_ARGS=()
if (($#)); then EXTRA_ARGS=("$@"); fi

log() { printf '[run-safe] %s\n' "$*" >&2; }

resolve_python() {
  local candidates=(
    "$ROOT/build/pyinstaller-venv-macos/bin/python"
    "$ROOT/build/pyinstaller-venv/bin/python"
    "$ROOT/.venv/bin/python"
  )
  local c
  for c in "${candidates[@]}"; do
    if [[ -x "$c" ]] && "$c" -c "import tenet, nacl" 2>/dev/null; then
      echo "$c"
      return 0
    fi
  done
  if command -v python3 >/dev/null && python3 -c "import tenet, nacl" 2>/dev/null; then
    echo python3
    return 0
  fi
  log "bootstrapping minimal venv at build/demo-venv (pip install -e .)..."
  python3 -m venv "$ROOT/build/demo-venv"
  "$ROOT/build/demo-venv/bin/pip" install -q -U pip wheel
  "$ROOT/build/demo-venv/bin/pip" install -q -e .
  echo "$ROOT/build/demo-venv/bin/python"
}

load_optional_env() {
  if [[ -f "$FRY_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$FRY_ENV"
    set +a
  fi
  if [[ -f "$ROOT/config/beta-secrets.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT/config/beta-secrets.env"
    set +a
  fi
}

have_key() {
  [[ -n "${ANTHROPIC_API_KEY:-}" ]]
}

maybe_record() {
  if [[ "$RECORD" == "1" ]]; then
    tee -a "$RECORDING"
  else
    cat
  fi
}

run_present() {
  local py="$1"
  log "present.py (stage screencast; real mixnet + narrated payment)"
  if ((${#EXTRA_ARGS[@]})); then
    "$py" "$ROOT/scripts/demo/present.py" --prompt "$PROMPT" "${EXTRA_ARGS[@]}"
  else
    "$py" "$ROOT/scripts/demo/present.py" --prompt "$PROMPT"
  fi
}

run_berlin() {
  local py="$1"
  if have_key; then
    log "berlin_pick.py (real mixnet + Claude expert)"
  else
    log "berlin_pick.py (real mixnet; transport-only — no ANTHROPIC_API_KEY)"
  fi
  if ((${#EXTRA_ARGS[@]})); then
    "$py" "$ROOT/scripts/demo/berlin_pick.py" --prompt "$PROMPT" "${EXTRA_ARGS[@]}"
  else
    "$py" "$ROOT/scripts/demo/berlin_pick.py" --prompt "$PROMPT"
  fi
}

run_replay() {
  if [[ ! -f "$RECORDING" ]]; then
    log "no recording at $RECORDING"
    return 1
  fi
  log "replaying saved transcript: $RECORDING"
  {
    echo ""
    echo "  ▟▛ TENET  —  replay (offline fallback)"
    echo "  ─────────────────────────────────────"
    echo ""
    cat "$RECORDING"
    echo ""
    echo "  [end replay — run ./scripts/demo/run-safe.sh MODE=berlin for live mixnet]"
    echo ""
  } | maybe_record
  return 0
}

run_sim_host() {
  local py="$1"
  log "bringing up sim host mesh ($SIM_SCENARIO)..."
  if ! "$py" -m sim up "$SIM_SCENARIO" --realization host --wait; then
    log "sim host up failed (non-fatal); continuing with berlin_pick only"
  else
    log "sim mesh up — nodes on loopback (see: $py -m sim status)"
  fi
  run_berlin "$py" "${EXTRA_ARGS[@]}"
}

run_sim_clients() {
  # Docker client-sim askers against pre-built linux binary (needs image + keys).
  # Falls back to berlin_pick if docker/image/key missing.
  local image="${IMAGE:-tenet-client-sim:latest}"
  if ! command -v docker >/dev/null 2>&1; then
    log "docker not available — falling back to berlin_pick"
    run_berlin "$(resolve_python)" "${EXTRA_ARGS[@]}"
  fi
  if [[ ! -x "$ROOT/dist/tenet-linux-x86_64" ]]; then
    log "missing dist/tenet-linux-x86_64 — falling back to berlin_pick"
    run_berlin "$(resolve_python)" "${EXTRA_ARGS[@]}"
  fi
  if ! have_key; then
    log "ANTHROPIC_API_KEY missing — client-sim needs key; falling back to berlin_pick"
    run_berlin "$(resolve_python)" "${EXTRA_ARGS[@]}"
  fi
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    log "building $image from dist/tenet-linux-x86_64..."
    IMAGE="$image" "$ROOT/scripts/build-client-sim-image.sh" || {
      log "client-sim image build failed — berlin_pick"
      run_berlin "$(resolve_python)" "${EXTRA_ARGS[@]}"
    }
  fi
  log "launching client-sim container(s) (linux/amd64 asker)"
  CLIENT_COUNT="${CLIENT_COUNT:-1}" IMAGE="$image" PROMPT="$PROMPT" \
    "$ROOT/scripts/run-client-sim.sh" || {
    log "client-sim run failed — berlin_pick"
    run_berlin "$(resolve_python)" "${EXTRA_ARGS[@]}"
  }
}

run_auto() {
  local py="$1"
  if have_key; then
    if run_present "$py" "${EXTRA_ARGS[@]}" | maybe_record; then
      return 0
    fi
    log "present.py failed — trying berlin_pick"
  else
    log "no ANTHROPIC_API_KEY — skipping present.py"
  fi
  if run_berlin "$py" "${EXTRA_ARGS[@]}" | maybe_record; then
    return 0
  fi
  log "live run failed — replaying recording"
  run_replay
}

dispatch() {
  local py="$1"
  case "$MODE" in
    present)
      have_key || { log "present needs ANTHROPIC_API_KEY — use MODE=berlin or MODE=replay"; return 2; }
      run_present "$py" "${EXTRA_ARGS[@]}"
      ;;
    berlin)
      run_berlin "$py" "${EXTRA_ARGS[@]}"
      ;;
    replay)
      run_replay
      ;;
    sim-host)
      run_sim_host "$py"
      ;;
    sim-clients)
      run_sim_clients
      ;;
    auto)
      run_auto "$py"
      ;;
    *)
      log "unknown MODE=$MODE (use auto|present|berlin|replay|sim-host|sim-clients)"
      return 2
      ;;
  esac
}

main() {
  local py rc=0
  py="$(resolve_python)"
  load_optional_env
  dispatch "$py" || rc=$?
  exit "$rc"
}

main
