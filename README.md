# tenet — the expert network

> **Planning, status, queue, live pins, and operations:** [`STATUS.md`](STATUS.md) only.
> Archived design docs: `~/fat/tenet-archive/docs/`.

**tenet routes a question to the peer most likely to answer it well.**

Most LLM setups ask one model, working from training data, every question.
tenet treats a network of participants — each with their own indexed knowledge
and domain focus — as a routing surface. When you ask a question, tenet finds
the peers whose local knowledge actually matches it, sends the question to one
of them, and streams the answer back.

The premise is plain: for a specialized question, the right specialist's
indexed library beats a general model guessing from memory. tenet is the routing
layer that connects the question to that knowledge.

This is an **expert-routing network** — not a chain, not a token, and not a
verification scheme.

## Why run a node

If you run a node, your own questions become routable to every other expert on
the network — and in exchange, your indexed knowledge becomes reachable by
others when it's the best match.

- **You don't expose your prompts.** Questions travel a multi-hop encrypted path.
- **Relays can't read traffic.** Only the chosen expert opens the question.
- **You don't publish your files.** Only a statistical **manifest** is public.
- **You don't need an open port.** Home nodes use a **reachability relay**.

## How it works

1. Index local knowledge into a **manifest**.
2. Register as an **expert peer** (REACH via relay if behind NAT).
3. When a question matches, the network routes it to you sealed.
4. You answer with local knowledge + a frontier model.
5. The answer streams back to the asker on a return path only they can read.

## Architecture

| Construct | Role |
|-----------|------|
| **Client** | Asks questions, receives answers; same binary for expert mode |
| **Expert peer** | Answers when its manifest matches |
| **Manifest** | Public statistical summary of expertise (not raw files) |
| **Directory** | Signed snapshot of peers and manifests |
| **Reachability relay** | Forwards sealed bytes to registered peers; no inspection |
| **Matcher + mailbox** | Oblivious match and delivery in Nitro TEE |

Full topology, queue (**items 1–15**), live URLs, and ops: [`STATUS.md`](STATUS.md).

## Quick start

> CLI package name is still `por`; rename to `tenet` is pending.

```bash
pip install -r requirements.txt
make smoke
python3 -m por --help
```

Live matcher check (items 4, 5, 9):

```bash
./scripts/verify-live.sh
python3 -m por enclave match --prompt "Tell me about Monet"
```

Everything else (expert, relay, Alpha population, item 13 send): [`STATUS.md`](STATUS.md) **Operations**.

## Project layout

```
por/                 Client, expert, and relay runtime
por/daemon/          Node entry points
tests/               Test suite
scripts/             Ops helpers (behavior only; status in STATUS.md)
examples/            Sample configs
```

## Building a release binary

```bash
python3 scripts/build_binary.py
```

## Testing

See [`STATUS.md`](STATUS.md) **Commands vs what they prove**.

```bash
make smoke
./scripts/verify-live.sh
pytest -q
```
