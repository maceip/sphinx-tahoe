# Demo And Harness Inventory

This repository has several demo surfaces. They are not equivalent.
None of them is a production P-OR daemon.

| Entry point | What it is | Network boundary | Provider/LLM |
| --- | --- | --- | --- |
| `demo.py` | Terminal UX simulation for Expert Mode planning and envelope flow | No sockets; `MixnetSim` direct calls | No real provider; harness reply |
| `python3 -m por.udp_demo demo` | Local UDP wire harness for Expert Mode | Localhost UDP datagrams, separate node processes | No real provider; harness reply |
| `python3 -m por.quic_demo demo` | Local QUIC wire harness for Expert Mode | Localhost QUIC/H3, separate node processes | No real provider; harness reply |
| `sim_mixnet_llm_roundtrip.py` | In-process simulator plus optional local LLM server | No sockets between relays; `MixnetSim` direct calls | Local Anthropic-compatible server |
| `sim_mixnet_anthropic_proxy.py` | HTTP proxy to Anthropic wrapped by `MixnetSim` | HTTP proxy socket only; relays are direct calls | Real Anthropic if configured |

Use "wire demo" only for `por.udp_demo` and `por.quic_demo`.
Use "sim" or "harness" for `demo.py`, `sim_mixnet_llm_roundtrip.py`, and
`sim_mixnet_anthropic_proxy.py`.

The UDP/QUIC demos prove local process/socket plumbing and trace shape. Their
responses are harness text, and their return path still needs the final per-hop
link-CID migration. Use `HYBRID_RETURN_PATH_SPEC.txt` and
`docs/por_wire_protocol.md` for the target wire.
