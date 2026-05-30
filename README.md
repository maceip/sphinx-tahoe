P-OR: Private Prompt Routing Network
=====================================

A mixnet-based prompt routing protocol for LLM inference. Forward path uses
Outfox (per-hop KEM + AEAD + LIONESS PRP). Return path uses symmetric circuit
streaming for low-latency token delivery.

Status
------

**Research prototype.** Crypto and packet format are complete. Production
runtime is in progress.

### What works

- **Outfox forward path**: per-hop KEM, AEAD headers, HKDF key derivation,
  LIONESS PRP payload, ML-DSA-65 signatures, timestamps, dummy traffic
- **Hybrid return path**: per-hop link CIDs (unlinkable), AES-CTR circuit
  streaming, nonce monotonicity, magic corruption detection, keepalive,
  auto-chunking, paced emission (TA mitigation)
- **SURB + circuit coexistence**: single-shot replies and streaming in same session
- **Expert Mode**: memory-fit discovery, route planning, envelope pipeline
- **Security proofs**: GDH, service model, nymserver elimination (Scherer 2023)
- **Daemons**: por-relay, por-expert with config, signal handling, provider calls
- **Provider calls**: Anthropic, OpenAI, harness mode (`POR_PROVIDER` env var)
- **Transport**: UDP demo (real sockets, separate processes), QUIC skeleton

### What doesn't exist yet

- Production persistent connections and NAT traversal
- HTTP/SSE gateway (`por-gateway`)
- Prompt hiding / proof-of-execution extensions
- Canonical binary wire framing (JSON frames still used in demos)

Architecture
------------

```
sphinxmix/           Packet crypto (Outfox, SURB, circuits, MixnetSim)
por/                 Application layer (envelopes, expert mode, daemons, transport)
por/daemon/          Production entry points (relay.py, expert.py)
docs/                Specs and architecture notes
```

Quick start
-----------

```bash
pip install -r requirements.txt

# Run tests
pytest test_outfox.py test_mixnet.py test_scherer2023_fixes.py test_a5_exit.py

# Run Expert Mode demo (no network, simulated)
python3 demo.py

# Run UDP wire demo (real sockets, separate processes)
python3 -m por.udp_demo demo

# Run with real LLM provider at exit
POR_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... python3 -m por.udp_demo demo
```

See `DEMOS.md` for the full demo inventory and what each one proves.

References
----------

- Rial, Piotrowska, Halpin (2025) "Outfox" (arXiv:2412.19937v2)
- Scherer, Weis, Strufe (2023) "Provable Security for Sphinx" (arXiv:2312.08028v1)
- Lazar et al. "Yodel" (constant-rate mixing)

Licence
-------

LGPL v3. Based on sphinxmix by Ian Goldberg and George Danezis (UCL).
