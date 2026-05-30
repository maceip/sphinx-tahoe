P-OR: Better Answers Through the Crowd
=======================================

P-OR is an expert routing network for LLM inference. Instead of asking one
model one question, P-OR finds peers on the network whose local memory and
domain expertise match your prompt, routes your question to them through an
encrypted relay chain, and streams the answer back.

The idea is simple: the crowd's memory is better than yours alone. A
construction engineer's indexed reference library produces a better answer
about load-bearing walls than a general-purpose model working from training
data. A culinary researcher's corpus knows more about Maillard chemistry
than a frontier chat completion.

Why would anyone run a node?
----------------------------

The natural question: why would I let strangers route prompts through my
machine?

Because you get access to the network's expertise in return. Running a node
makes your own prompts routable to every other expert on the network. The
more specialized knowledge you contribute, the more specialized knowledge
you can access.

The network protects participants:

- **Sender anonymity**: multi-hop encrypted relay chain (each relay only
  sees the previous and next hop, never the sender or the expert)
- **Prompt confidentiality**: only the selected expert peer sees the prompt
  content; relay nodes see encrypted bytes
- **Expert privacy**: memory manifests publish statistical summaries and
  Merkle commitments, not raw text or file paths
- **Replay rejection**: per-layer timestamps and monotonic nonce counters
- **Integrity**: ML-DSA-65 post-quantum signatures on forward payloads

How it works
------------

1. Your client indexes local memory (documents, notes, corpora) into a
   manifest describing what you know, not what you have
2. You register on the network as an expert peer
3. When someone's prompt matches your expertise, the network routes it
   to you through encrypted relays
4. Your node combines the prompt with your local knowledge and a frontier
   LLM to produce a domain-specific answer
5. The answer streams back through a symmetric circuit to the sender

Quick start
-----------

```bash
pip install -r requirements.txt

# Run tests
pytest tests/

# Run Expert Mode demo (simulated, no network)
python3 scripts/demo.py

# Run wire demo (real UDP sockets, separate relay processes)
python3 -m por.udp_demo demo

# Run with real LLM at the expert exit
POR_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... python3 -m por.udp_demo demo
```

Project structure
-----------------

```
sphinxmix/           Packet crypto and in-process simulator
por/                 Application layer (expert mode, envelopes, transport)
por/daemon/          Production node entry points
tests/               Test suite (120 tests)
scripts/             Demos, sim proxies, CI scripts
docs/                Specs and architecture notes
```

References
----------

- Danezis, Goldberg (2009) "Sphinx: A Compact and Provably Secure Mix Format"
- Rial, Piotrowska, Halpin (2025) "Outfox: a Postquantum Packet Format for Layered Mixnets" (arXiv:2412.19937v2)
- Scherer, Weis, Strufe (2023) "Provable Security for the Onion Routing and Mix Network Packet Format Sphinx" (arXiv:2312.08028v1)
- Lazar, Zeldovich (2019) "Yodel: Strong Metadata Security for Voice Calls"
- Diaz, Murdoch, Troncoso (2021) "Systematizing Decentralization and Privacy: Lessons from 15 Years of Research and Deployments" (Nym mixnet)
- Buterin, Feist, Wahrstatter, et al. (2025) "Proof of Complete Knowledge" (arXiv)

Licence
-------

LGPL v3. Based on sphinxmix by Ian Goldberg and George Danezis (UCL).
