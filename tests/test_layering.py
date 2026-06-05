"""Architecture enforced as a test, not a document.

Dependencies point DOWN only. Each module's layer is its folder; a module may
import its own layer or lower, never higher. The substrate (packet, base,
mixnet, enclave) can never import a capability or edge.

This is the rule that would have caught the p2p-search work that assumed it
could connect to an expert directly: connectivity goes over the mixnet, so a
capability holds an opaque handle, not a peer id. The folder a contributor drops
their module into *is* its layer, and CI checks the import direction.

ALLOWLIST is current debt — empty means the layering is clean.
"""

from __future__ import annotations

import ast
import pathlib

TENET = pathlib.Path(__file__).resolve().parent.parent / "tenet"

# Layer order: a module may import layers <= its own.
PACKET, BASE, MIXNET, ENCLAVE, CAPABILITY, EDGE = 0, 1, 2, 3, 4, 5
BASE_MODULES = {"config", "log_events", "envelope", "handles"}  # tenet/<name>.py


def _layer_of_module(dotted: str) -> int | None:
    """Layer for a tenet.* dotted module path (None if not a tenet module)."""
    parts = dotted.split(".")
    if not parts or parts[0] != "tenet" or len(parts) < 2:
        return None
    top = parts[1]
    if top == "packet":
        return PACKET
    if top == "mixnet":
        return MIXNET
    if top == "enclave":
        return ENCLAVE
    if top in {"experts", "llm"}:
        return CAPABILITY
    if top == "edges":
        return EDGE
    if top in BASE_MODULES:  # tenet.config etc. (leaf module at the root)
        return BASE
    return None


def _layer_of_path(path: pathlib.Path) -> int | None:
    rel = path.relative_to(TENET)
    parts = rel.with_suffix("").parts
    if len(parts) == 1:  # tenet/<name>.py
        return BASE if parts[0] in BASE_MODULES else None
    return _layer_of_module("tenet." + ".".join(parts))


def _imported_tenet_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.startswith("tenet"):
                out.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("tenet"):
                    out.add(alias.name)
    return out


LAYER_NAMES = {0: "packet", 1: "base", 2: "mixnet", 3: "enclave", 4: "capability", 5: "edge"}

# Upward edges still present. Empty == clean. Add (importer_module, imported_module).
ALLOWLIST: set[tuple[str, str]] = set()


def test_dependencies_point_down_only():
    violations: set[tuple[str, str]] = set()
    for path in TENET.rglob("*.py"):
        if path.name == "__init__.py" or path.name == "__main__.py":
            continue
        own = _layer_of_path(path)
        if own is None:
            continue
        importer = "tenet." + ".".join(path.relative_to(TENET).with_suffix("").parts)
        for imported in _imported_tenet_modules(path):
            target = _layer_of_module(imported)
            if target is not None and target > own:
                violations.add((importer, imported))

    unexpected = violations - ALLOWLIST
    stale = ALLOWLIST - violations
    assert not unexpected, (
        "upward import(s) — a module imported a higher layer. The substrate must "
        f"never depend on a capability/edge: {sorted(unexpected)}"
    )
    assert not stale, f"allowlist entries no longer exist — delete them: {sorted(stale)}"
