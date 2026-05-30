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

# Unified binary shape
python3 -m por --help
python3 -m por run --config por-config.json

# Run with real LLM at the expert exit
POR_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... python3 -m por.udp_demo demo
```

Project structure
-----------------

```
sphinxmix/           Packet crypto and in-process simulator
por/                 Application layer (expert mode, envelopes, transport)
por/daemon/          Production node entry points
tests/               Test suite
scripts/             Demos, sim proxies, CI scripts
docs/                Specs and architecture notes
```

Home client shape
-----------------

The product path is `python3 -m por run --config client.json`. A home client
does not need an inbound listener and should not paste an expert IP address into
config. It loads a public directory snapshot, verifies the selected expert's
signed `peer_address` record, and dials a trusted reachability relay.

```json
{
  "node_id": "client-home",
  "role": "client",
  "client": {
    "directory_snapshot": "https://directory.example/snapshot",
    "trusted_reachability_relays": [
      {
        "relay_id": "bootstrap-1",
        "host": "203.0.113.10",
        "port": 4433,
        "verify_key": "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
      }
    ],
    "local_http": {
      "enabled": true,
      "bind": {"host": "127.0.0.1", "port": 8766},
      "path": "/v1/expert",
      "status_path": "/v1/status"
    }
  },
  "peer_address": {"enabled": true}
}
```

Current MVP note: `verify_key` verifies `PeerAddressRecord` signatures. In this
Python harness the record signature is HMAC-based; the field is intentionally
named as a verification key so the wire format can move to public-key
signatures later without changing client config shape.

Client logs use stable event names such as `peer_address_plan`, `dial_target`,
and `peer_address_rejected`. These logs include peer IDs, relay IDs, hosts, and
ports needed for operations; they must not include prompt text.

Supernode block
---------------

A reachability relay is still the same `por` binary. In config it is a relay
daemon promoted with `supernode` flags; the daemon key, `node_id`, and client
trusted relay `relay_id` must match.

```json
{
  "daemons": {
    "client-home": {
      "role": "client",
      "client": {
        "trusted_reachability_relays": [
          {
            "relay_id": "bootstrap-1",
            "host": "203.0.113.10",
            "port": 4433,
            "verify_key": "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
          }
        ]
      },
      "peer_address": {"enabled": true}
    },
    "bootstrap-1": {
      "role": "relay",
      "transport": {"kind": "udp", "host": "0.0.0.0", "port": 4433},
      "supernode": {
        "enabled": true,
        "public_ip": "203.0.113.10",
        "advertise_relay": true,
        "register_directory": true,
        "accept_inbound_mix": true
      }
    }
  }
}
```

Run shape for the promoted relay/supernode and home client:

```bash
python3 -m por run --config examples/home-client-supernode.config.json --node-id bootstrap-1
python3 -m por run --config examples/home-client-supernode.config.json --node-id client-home
```

Test groups
-----------

The test suite uses pytest markers so crypto regressions and product paths do
not blur together:

```bash
# Product/runtime acceptance paths
pytest -m product

# Packet-crypto and simulator regressions
pytest -m crypto

# Multi-process or threaded runtime checks
pytest -m integration
```

Product tests cover the unified `por` binary, persistent client session, local
HTTP/SSE chunk streaming, structured runtime logs, public directory snapshots,
JSON health/status surfaces, and binary UDP wire integration. Crypto tests
cover the underlying Outfox / Sphinx-style packet behavior and simulator
invariants.

Release binary
--------------

Build one executable per platform with PyInstaller from that platform:

```bash
python3 scripts/build_binary.py
```

On Apple Silicon macOS this writes `dist/por-macos-arm64`. The executable
contains the Python runtime and project dependencies, so the user-facing install
shape is download one file, make it executable if needed, and run:

```bash
./por-macos-arm64 --help
./por-macos-arm64 run --config client.json
```

Builds are platform-local: run the same script on Linux and Windows runners to
produce `por-linux-*` and `por-windows-*` release artifacts. macOS release
publishing still needs normal Developer ID signing and notarization outside this
script.

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
