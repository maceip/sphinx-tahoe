# Agent instructions

## Cursor Cloud specific instructions

**tenet** (expert-routing network; Python package/CLI still named `por`) is a single Python 3 project. There is no Node.js, Docker Compose, or Makefile-based app bootstrap—see `README.md` for product context.

### PATH and installs

`pip install` places console scripts (`por`, `pytest`, etc.) in `~/.local/bin`. Cloud VMs should have `export PATH="$HOME/.local/bin:$PATH"` in the shell (or use module invocations below).

The VM **update script** (startup dependency refresh) is:

```text
python3 -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e . pytest pytest-cov
```

### Verify the environment

| Check | Command |
|-------|---------|
| Doc claims guard | `python3 scripts/check_ta_claims.py` |
| Full test suite | `pytest -q` (see known failures below) |
| Product acceptance | `pytest -q -m product` |
| Coverage (CI gate) | `pytest -q --cov=por` (requires ≥78% in `pytest.ini`) |
| UX simulation (no network) | `printf '\n' \| python3 scripts/demo.py` (stdin empty → default Monet prompt) |
| Wire harness (UDP subprocesses) | `python3 -m por.udp_demo demo` |
| Unified CLI | `python3 -m por --help` |

Prefer `python3 -m por …` and `python3 -m pytest` if `~/.local/bin` is not on `PATH`.

### Lint

No ruff/flake8/mypy is configured. The only doc/consistency guard is `scripts/check_ta_claims.py` (also run via `tox`).

### Running services (manual / production-shaped)

End-to-end **pytest** uses `tests/harness.py` on localhost—no external directory or API keys. For manual multi-process runs, start `por directory`, `por relay`, `por expert`, and `por run` per `README.md` and `examples/`. Default LLM is the in-process **harness** (`POR_PROVIDER=harness`); real models need `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

`examples/home-client-supernode.config.json` references `examples/directory-snapshot.json`, which is not committed; generate a snapshot in tests or serve one with `por directory`.

### Known test failures on current `master`

Two tests fail without extra setup (not an install problem):

1. **`tests/test_mixnet.py::test_exit_with_api_call`** — expects an Anthropic-compatible HTTP server on `127.0.0.1:8000` (e.g. `python3 scripts/sim_mixnet_anthropic_proxy.py` with `ANTHROPIC_API_KEY`).
2. **`tests/test_por_platform.py::test_relay_and_expert_cluster_entrypoints_emit_start_log`** — `WireNodeRuntime.__init__()` does not accept `provider=` passed from `por/daemon/expert.py` (code/API mismatch).

**Product** tests (`pytest -m product`) pass without external services.

### Optional: release binary

`python3 scripts/build_binary.py` → `dist/por-<platform>-<arch>` (PyInstaller; needs extra deps if not already installed).

### Workspace rule: FRISCY constitution

If you are validating Friscy webshell/rootfs behavior in this repo, follow `.cursor/rules` (webshell-only execution, output-gated checkpoints, etc.). Normal Python development in this Cloud VM uses the host shell above.
