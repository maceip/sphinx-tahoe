# Matcher & Discovery — Threat Model, Trust Decision, and Transport Schematics

Status: **decided** (architecture review, 2026-06-01). Single trust model
locked: **oblivious TEE-backed central services**. Outfox is demoted to
sealed-transport plumbing. Decentralization is a **temporal** migration
substrate, never a concurrent second trust plane.

This doc reconciles the discovery/matching layer with the underlying transport
(`sphinxmix/Outfox*`, `por/node_runtime.py`, `por/daemon/supernode.py`). It
supersedes nothing in `supernode_threat_model.md`; it explains why that doc's
"reachability relay is trusted for metadata" stance is no longer load-bearing
for anonymity (the TEE provides linkage-hiding; the relay becomes plumbing).

---

## 0. The keystone thesis (why this system can exist now)

Every prior metadata-private routing/messaging system (Vuvuzela → Stadium →
Karaoke → Groove → TEEMS; PIR systems like Tiptoe/Sabre) treats a routing or
delivery **miss as a failure** — a dropped message, a wrong PIR row. Correctness
is mandatory, and correctness is what forces the expensive machinery (global
cover traffic, exact PIR, non-collusion across many operators).

**This system is the first where a miss is not a failure.** Route to the wrong
expert and the prompt still gets a frontier-model answer — a *soft* degradation,
never a denial of service. That single fact demotes the discovery layer from a
**correctness** problem to a **quality** problem, which is the regime where the
cheap, private, single-operator options live (coarse manifests, oblivious-but-
lossy matching, DP-noised queries).

> The frontier model did not make a specialist network redundant — it made a
> **private** one affordable. Because every miss is caught, the router is
> *allowed to be lossy*, and lossy is where privacy gets cheap.

This is only ~2 years old, because the floor (a frontier LLM good enough to
backstop a miss) is what is new.

**The corrosion risk this same floor creates:** because everything always
answers, bad routing produces no visible error — the network can hollow into
"slow frontier with extra steps." The load-bearing instrument against this is
**expert win-rate over the frontier baseline**: the fraction of routed queries
where the expert beat what the frontier model alone would have said. That single
number is the quality signal, the reputation signal, the matching-improvement
training labels, and the degradation alarm. Instrument it from day one.

---

## 1. The two invariants (load-bearing — do not let these erode)

**I1 — Security level is a property of the NETWORK at a point in time, never of
the USER.** There is no "high-security mode," no cover-traffic flag, no opt-in
hardening. Any opt-in security feature *fragments the anonymity set*: the users
who flip it become a smaller, distinguishable cohort, so the feature makes them
*easier* to single out. One level, everyone, always. (Concrete consequence:
cover traffic, if/when added, is network-wide or absent — never a per-client
toggle.)

**I2 — Migration flips the network, never forks the users.** Exactly one trust
model is live for everyone at any instant. The mixnet is a dormant substrate +
a migration plan, not a second live plane. You change the trust model by flipping
the whole network (or a whole federation), never by letting a user pick a
different trust model per request.

The rejected pattern (for the record): "add a flag to turn on fake-packet-rate
sending for clients who want more security." That violates I1. The accepted
pattern: Outfox + Yodel-style self-healing return circuits — different mechanisms
for different jobs inside **one** trust model (mechanism-hybrid, fine).

---

## 2. The trust decision

**Locked: one trust model = oblivious TEE-backed central services.** You trust
the hardware + remote attestation + our oblivious code — **not** the operator.
The operator's OS sees only sealed bytes, IPs, and timing.

Why not the alternatives:

- **(a) Mixnet-only** — its bootstrap anonymity is *vacuous*: we run essentially
  all the relays, so a single party (us) sees both ends. A mixnet's unlinkability
  needs many non-colluding operators we do not have and (per Farcaster) may never
  get. Rejected as the *sole* model.
- **(c-concurrent) Per-request trust dial / two app versions** — violates I1/I2;
  unmaintainable; security becomes a per-request property. Rejected.
- **(b → c-temporal) Oblivious TEE central, with the mixnet as a temporal
  migration substrate** — *accepted.* Dissolves the bootstrap non-collusion
  problem (a single operator can run private discovery and still not link;
  Signal ships exactly this for contact discovery), ships low latency (good for
  interactive inference), and the discovery loss it induces is free because of
  the keystone floor.

### Prior art this rests on

- **TEEMS** (PoPETs 2025, Sasy/Johnson/Goldberg) — oblivious TEE mailbox;
  **ID channel** delivers to a known ID with *no prior coordination* (the
  stranger-rendezvous primitive Groove lacked). Source of the mailbox design.
- **Sparta** (S&P 2025, UCSC) — deferred-retrieval oblivious mailbox; the
  storage-engine lineage; explicitly aligned with Signal's SGX + oblivious
  contact discovery (the production proof point).
- **Groove** (OSDI 2022, Barman et al.) — oblivious *delegation* lets an
  untrusted provider do the rigid mixnet work for a mobile client. Key lesson:
  the untrusted-provider guarantee is *parasitic on a real mixnet* (batch +
  shuffle + noise). It also requires pre-shared buddy secrets (no discovery), so
  it does not solve our core gap — but it is why we do not pretend a half-built
  mixnet buys us untrusted relays.

### The honest critique (the "Lazar club"), stated so we are ready for it

1. *A TEE is trust-relocation, not anonymity — and it fails correlated and
   catastrophic: one hardware break de-anonymizes everyone at once, where a
   mixnet degrades gracefully with the honest fraction.* True. Our answer: the
   frontier floor makes a de-anon a **privacy** breach, not a **service**
   outage; and the migration substrate (I2) is the hedge if the hardware bet
   ages badly.
2. *Your migration is vaporware — nobody decentralizes.* Also true (Farcaster).
   So we do not sell it; we keep it *possible*, assume TEE-central is likely
   permanent, and under-promise.

### Who we deliberately do not serve

The no-hardware-trust maximalist. Serving them means a second live trust model,
which violates I1/I2. We pick the user who will trust audited hardware +
attestation over trusting us, and we serve them completely.

---

## 3. Topology

```
┌───────────── ONE OPERATOR, ONE DATACENTER ─ TRUST = hardware + attestation + oblivious code ─────────────┐
│                       (the operator's OS sees only sealed bytes, IPs, timing — never content or linkage) │
│                                                                                                          │
│   ┌────────────┐        ┌───────────────────┐        ┌───────────────────┐                               │
│   │ INGESTION  │        │   MATCHER enclave  │        │   MAILBOX enclave  │                              │
│   │ enclave    │──────▶ │  oblivious k-NN    │        │  oblivious ID-     │                              │
│   │ authN(ARC) │        │  over manifests    │        │  channel routing   │                              │
│   └────────────┘        └───────────────────┘        └─────────┬─────────┘                               │
└───────▲───────────────────────────▲─────────────────────────────│───────────────────────────────────────┘
        │①sealed query+ARC           │②top-K opaque handles         │④ sealed bytes
        │                            │                              ▼
   ┌────┴─────┐                 (back to asker)            ┌──────────────────┐
   │  ASKER   │◀─────────────────────┘                     │ REACHABILITY     │  sees: enclave ↔ expert
   │  client  │                                            │ relay  (NAT only)│  NOT the asker
   │ (thin,   │──③ sealed msg → opaque handle ────────────▶│ sealed forward   │
   │ identical)│                                           └─────────┬────────┘
   └────▲─────┘                                                      │⑤ sealed bytes
        │                                                            ▼
        │                                                      ┌───────────┐
        │⑥ answer streams back (Yodel self-healing circuit)    │  EXPERT   │ opens query, answers
        └──── MAILBOX enclave ◀──── relay ◀──────────────────── │  client   │ (corpus + frontier floor)
              (oblivious route, only asker can decrypt)         └───────────┘
```

Registration (expert side): the expert registers a coarse opaque-embedding
manifest with the Matcher enclave (oblivious) and a reachability mapping with the
relay (the relay learns the expert's IP — unavoidable for NAT). The two are
bridged only by an **opaque handle** the Matcher cannot reverse to a relay/IP.

---

## 4. Transport schematic — who sees what

| Party | Sees | Cannot see |
|---|---|---|
| **Operator OS** (host) | IPs connecting, sealed bytes, timing/volume | query content, match result, **asker↔expert link** |
| **Matcher enclave** | query vector + manifests, via *oblivious* access | nothing persists; access pattern leaks nothing; ephemeral |
| **Mailbox enclave** | opaque handles, sealed msgs, *oblivious* route | who↔who linkage |
| **Reachability relay** | enclave ↔ expert, sealed bytes | asker identity, content |
| **Expert** | the query (it must, to answer), opaque return handle | asker IP/identity |
| **Asker** | the answer, opaque expert handle | expert IP |

The only plaintext query exists *inside the expert*; the only cleartext match
exists *inside the enclave*. Everything on the wire is sealed.

**Residual (network-level participation):** the operator learns "IP X uses
tenet," not what or with whom. Hiding that needs uniform cover traffic, which by
**I1** is network-wide or absent — never a per-client flag.

---

## 5. Adversary → linkage scorecard

| # | Concern | Status under this design |
|---|---|---|
| 1 | Relay sees both ends | **Closed by the TEE**, not by mix hops. Oblivious mailbox routing hides asker↔expert; the relay only ever sees enclave↔expert. (Under the old mixnet-only framing this was an *accepted* metadata-trust leak; it is now removed.) |
| 2 | Bootstrap anonymity set ≈ 1 operator | **Dissolved.** Oblivious enclaves let the single operator run discovery without being able to link. Non-collusion across operators is no longer required for anonymity. |
| 3 | No real mixing (timing/GPA) | **Out of scope, explicitly.** We serve the operator/network/server-OS adversary, not a global passive timing adversary. The Outfox mix is plumbing, not the anonymity source. |
| 4 | Fused identity / structured handle | **Requirement:** handles are opaque, relay-resolvable, rotatable tokens — not `(relay, peer_id)` tuples. The Matcher holds only the opaque token. |
| 5 | ARC/PP credential unlinkability | **Solved in design, critical pitfall in code.** The enclave rate-limits obliviously but still needs an unlinkable, single-use credential; reuse, or a fallback to per-IP throttling under load, silently re-links queries. ARC preferred over vanilla Privacy Pass (one credential, many presentations, rate-limited per epoch — fits the multiple Matcher touchpoints without a token-fetch storm). |

---

## 6. Temporal migration strip (I2 in one picture)

```
 PHASE 1  ── TEE-CENTRAL (now) ───────▶ PHASE 2 ── FEDERATION ─────────▶ PHASE 3 ── TRUSTLESS (if ever)
 we run the enclave plane.             many independent operators run    trust MIGRATES: mixnet provides
 trust = hardware+attestation.         the IDENTICAL enclave node;        anonymity, TEE optional/legacy.
 mixnet = dormant substrate.           same trust KIND, less concentrated. (may never happen — kept possible,
 ── ONE live model ──                  ── ONE live model ──                not promised.) ── ONE live model ──

 RULE (I2): migration = flip the whole network (or a whole federation). NEVER fork the users into two live models.
```

---

## 7. Deployment & cost

- The enclave plane runs on **cloud confidential computing** (e.g. Azure DCsv3
  SGX, or a confidential VM via SEV-SNP / TDX), not our bare metal — this pushes
  Intel's out-of-band TCB-recovery / microcode / attestation lifecycle onto the
  cloud provider. We *consume* attestation; we do not *operate* SGX provisioning.
  Cost becomes predictable enclave-VM opex.
- Prototype recommendation: build on a **confidential VM** for speed (near-
  unmodified software), but keep the matching/routing logic in **oblivious
  algorithms** regardless — the strong guarantee comes from oblivious-algos-
  inside-TEE, not the TEE alone — so the option to tighten down to an SGX enclave
  later survives without redesign.
- The mixnet substrate runs on commodity hardware; decentralization never
  requires every node to have a TEE.

---

## 8. Build order

1. **Opaque handle as a token (#4)** — small, foundational; unblocks oblivious
   routing and keeps the Matcher unable to reverse a handle to an IP.
2. **Enclave Matcher** — oblivious k-NN over coarse opaque-embedding manifests in
   a confidential VM. This is the matcher arch we were going to build anyway,
   placed inside the enclave. Fixes #2 and gives query-privacy (replaces the PIR
   plan). Instrument win-rate-over-frontier here from day one.
3. **Enclave mailbox / ID-channel** — oblivious routing (TEEMS blueprint);
   closes #1 for transport.
4. **Outfox mixnet** — left as sealed-transport plumbing (NAT delivery + Yodel
   return streaming). Do **not** invest in real mixing (#3) now; revisit only if
   relay diversity ever makes Phase 3 real.

---

## 9. What this does NOT solve

- Matching **quality** (win-rate) — orthogonal; the Matcher's job, gated on the
  outcome-feedback loop.
- Sybil/quality resistance on the expert set and on a future Matcher quorum.
- The global passive timing adversary (#3) — deliberately out of scope.
- A user's own seized device — their corpus predates us; we add no plaintext
  expertise label (the manifest is an opaque embedding), but we cannot make
  possessing the knowledge undetectable on their own machine.
