"""Architecture enforced as a test, not a document.

The substrate (base types, the mixnet, the enclave host) must never import an
application concern (a capability or an edge). This is the rule that would have
caught the p2p-search work that assumed it could connect to an expert directly:
connectivity goes *over the mixnet*, so a capability holds an opaque handle, not
a peer id. A capability may import the substrate (downward); the substrate may
never import a capability (upward).

The ALLOWLIST below is current debt — each entry is an upward edge a planned
seam removes. When a seam lands, delete its allowlist line; this test then makes
the boundary permanent. When the allowlist is empty, the substrate is pure.
"""

from __future__ import annotations

import ast
import pathlib

POR = pathlib.Path(__file__).resolve().parent.parent / "por"

# --- the five archetypes, by current module name (folders make this implicit later) ---
BASE = {"config", "log_events", "envelope", "handles"}  # pure types/util; everyone may import
MIXNET = {  # the sealed-routing substrate
    "node_runtime", "wire_frame", "reach_wire", "transport_dial", "quic_transport",
    "quic_runtime", "reach_client", "peer_address", "supernode", "upnp",
}
ENCLAVE = {  # the attested-workload host + attestation
    "enclave_attest", "attested_transport", "enclave_plane", "enclave_plane_server", "arc",
}
SUBSTRATE = BASE | MIXNET | ENCLAVE

APP = {  # capabilities + edges — the substrate must NOT reach up into these
    "matcher", "oblivious", "cover", "directory", "memory_index", "expert_route",
    "expert_mode", "expert_groups", "alpha_experts", "client", "live_client",
    "live_enclave", "live_expert", "provider", "join_pack", "cli_display",
    "gate_b_nodes", "gate_b_topology",
}

# Upward edges still present. Delete a line when its seam lands.
ALLOWLIST = {
    ("config", "expert_mode"),             # Seam C — config must not know experts
    ("node_runtime", "provider"),          # Seam A — mixnet must not call the LLM
    ("enclave_plane", "directory"),        # Seam B — enclave host must not import experts
    ("enclave_plane", "expert_route"),     # Seam B
    ("enclave_plane", "memory_index"),     # Seam B
    ("enclave_plane_server", "matcher"),   # Seam B
    ("enclave_plane_server", "directory"), # Seam B
}


def _imported_leaves(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    leaves: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is None:  # from . import X  /  from .. import X
                for alias in node.names:
                    leaves.add(alias.name.split(".")[0])
            elif node.level > 0:  # from .X import / from ..X import
                leaves.add(node.module.split(".")[0])
            else:  # from por.X import / from a.b import
                mod = node.module[4:] if node.module.startswith("por.") else node.module
                leaves.add(mod.split(".")[-1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("por."):
                    leaves.add(alias.name[4:].split(".")[0])
    return leaves


def test_substrate_never_imports_an_app_concern():
    violations: set[tuple[str, str]] = set()
    for name in SUBSTRATE:
        path = POR / f"{name}.py"
        if not path.exists():
            continue
        for leaf in _imported_leaves(path):
            if leaf in APP:
                violations.add((name, leaf))

    unexpected = violations - ALLOWLIST
    stale = ALLOWLIST - violations
    assert not unexpected, (
        "substrate reached up into an app concern (separate it — the substrate "
        f"cannot depend on a capability/edge): {sorted(unexpected)}"
    )
    assert not stale, (
        f"allowlist entries no longer exist — delete them to lock the boundary: {sorted(stale)}"
    )
