# tenet — Hackathon Submission (Algorand x402 Pitch Competition)

Copy-paste answers for each form field. Fields marked **[YOU FILL]** need
your personal/team info or links you control. Everything else is drawn
straight from the code in this repo.

---

### First Name* / Last Name* / Email*
**[YOU FILL]** — (suggested email: ryan.macarthur@gmail.com — confirm)

### Telegram Username*
**[YOU FILL]** — e.g. https://t.me/yourhandle

### X (Twitter) Project Profile*
**[YOU FILL]** — create a project profile (e.g. https://x.com/tenet_network) rather than a personal one

---

### Project name*
```
tenet
```
(GitHub repo is `sphinx-tahoe`; the product/package name is `tenet`.)

---

### Project one-liner*
```
tenet is a privacy-preserving expert network where AI agents pay in EURD over x402 on Algorand for trustworthy, reputation-weighted expert recommendations — no ads, no SEO, no single bribable expert.
```

---

### Project Description*
```
Problem. You can't trust SEO-, ad-, or affiliate-ranked answers, and AI agents
now make purchasing and recommendation decisions at scale with no trustworthy,
machine-payable source of expert judgment. A single expert (human or model) can
be bribed; a public reputation score can be gamed.

What tenet is. tenet is an expert network: ask a question once, route it
privately to the people or agents whose knowledge best matches it, and get an
answer over sealed transport. On top of that network we built Expert Pick — a
paid "which option should I choose?" service whose anti-gaming guarantee is
reputation-weighted multi-expert consensus: corrupting one expert does nothing,
because you'd have to corrupt a reputation-weighted majority, and flagged
experts are down-weighted to zero. Every pick ships with the experts'
conflict-of-interest disclosures.

Target users. (1) AI agents doing agentic commerce that need to pay for and
trust an expert decision; (2) people who want a recommendation they can trust
instead of an ad; (3) experts who want their knowledge to become reachable and
monetizable without publishing their data or opening a public port.

How it uses x402 + Algorand. Expert Pick is gated by x402 (HTTP 402 Payment
Required). The merchant answers an unpaid request with a 402 carrying x402
`accepts` requirements; the agent pays and resubmits an X-PAYMENT proof; the
server verifies settlement and returns the consensus pick. Payment settles in
Quantoz EURD — a MiCA-compliant euro stablecoin — over the Quantoz EURO→Algorand
bridge to a whitelisted Algorand address, and the merchant independently
confirms the EURD asset transfer landed on-chain via the Algorand indexer
(replay-protected). A second rail issues unlinkable, prepaid rate-limit tokens:
an x402 endpoint returns HTTP 402 with Algorand payment requirements, the client
pays on Algorand (real testnet ALGO/USDC; mainnet USDC slots into the same
shape), the server verifies the on-chain transaction via algod/indexer and
blind-signs (RFC 9474 blind-RSA) the client's token — so payment is provably
made yet unlinkable from spend, with nullifier-based double-spend prevention.
Execution honesty is two-tiered: a soft tier (reputation + spot-audit) for any
laptop expert and an attested tier (cloud-TEE signature) the asker verifies
offline.
```

---

### Please outline all members of your team*
**[YOU FILL]** — Format: `Name, email, role, background/previous experience.`
```
Ryan Macarthur, ryan.macarthur@gmail.com, <role e.g. Founder/Eng>. <background>
<Add other teammates one per line>
```

---

### Main track*
**Recommended:** the **Agentic Commerce / AI Agents + x402 payments** track
(tenet is AI agents paying for expert judgment over x402). Pick that option in
the dropdown; if it's worded as "Payments" or "x402", that also fits.

---

### Project stage*
```
Existing project (expanded for the hackathon)
```

---

### What was added during the scope of the hackathon*
```
Original status (before the hackathon). tenet was a working, live expert-routing
mixnet: Sphinx/Outfox sealed-transport packets, a Nitro-TEE oblivious matcher
with attested TLS and SPKI pinning, a public reachability relay, and two live
remote experts answering real queries end-to-end. It had deliberately NO
payments, no payouts, and no on-chain anything — compensation was explicitly
deferred until there was a real payment contract.

Added during the hackathon (the entire agentic-commerce payment + trust layer):
1. x402 protocol core (tenet/x402.py, tenet/x402_http.py): full HTTP 402
   challenge/verify flow with PaymentRequirements / PaymentPayload, fail-closed
   on-chain verification, and a threaded 402-protected token server.
2. Algorand rail (tenet/algorand.py): real algod/indexer adapters; build, sign,
   submit and confirm native-ALGO and ASA (USDC) payments on testnet; a txid→
   confirmed-transaction lookup injected into x402 verification.
3. Quantoz EURD adapter (tenet/quantoz.py): a Python port of the x402-euro-eurd
   integration — accept and pay EURD (MiCA euro stablecoin) over the Quantoz
   EURO→Algorand bridge, plus a real merchant-side on-chain settlement verifier
   that watches its Algorand address for the incoming EURD transfer and burns
   the txid against replay.
4. Expert Pick service (tenet/expert_pick.py, tenet/pick_server.py): an
   x402-gated recommendation API with reputation-weighted multi-expert consensus
   (weighted plurality + Borda ranking, flagged experts excluded), disclosures,
   and a real Anthropic LLM adapter.
5. Anonymous payment tokens (tenet/blind_rsa.py, tenet/rate_token.py): RFC 9474
   blind-RSA issuance so a paid token is unlinkable from its spend, with
   nullifier + per-epoch cap for double-spend / sybil control.
6. Two-tier execution honesty (tenet/honesty.py, tenet/vouchers.py): an
   unforceable asker challenge and offline receipt verification, soft
   (reputation/audit) vs attested (cloud-TEE) tiers.
7. Runnable demos: scripts/x402_algorand_demo.py (LIVE testnet payment unlocks
   an anonymous token), scripts/expert_pick_demo.py (402 → EURD pay → consensus
   pick), scripts/demo_phase1.py (pay → issue → spend → honesty-check →
   double-spend blocked), all with passing tests.

Why it matters. This turns a privacy-preserving expert network into an
agentic-commerce primitive: machine-payable, trust-minimized expert judgment
settled in a compliant euro stablecoin on Algorand — the missing "pay an expert
you can trust" step for AI agents.
```

---

### Bonus Tracks (select up to 2)
- **Quantoz Bonus Prize** ✅ — we integrate Quantoz EURD end-to-end (402
  `accepts`, EURO→Algorand bridge payment, on-chain settlement verification).
- (Second slot: leave blank — Folks Finance and Alpha Arcade aren't a fit.)

---

### Pitch deck (5–6 slides)*
**[YOU FILL]** — link (see suggested outline at the bottom of this file)

### Demo video (3–5 min)*
**[YOU FILL]** — link (see suggested demo script at the bottom)

### GitHub Repository URL*
```
https://github.com/maceip/sphinx-tahoe
```

### Project URL (live demo)
**[YOU FILL]** — optional; if you stand up the x402 endpoint publicly, paste it.
Live matcher already runs at the pinned enclave URL in config/live-enclave.json.

### Marketing consent checkbox
**[YOU DECIDE]** — optional.

---

## Suggested 6-slide pitch deck
1. **Problem** — AI agents transact at scale but have no trustworthy, payable
   source of expert judgment; SEO/ads/single experts are gameable/bribable.
2. **Solution** — tenet: x402-paid Expert Pick over a privacy-preserving expert
   network; trust = reputation-weighted multi-expert consensus.
3. **How x402 + Algorand fit** — 402 challenge → EURD payment over the Quantoz
   Algorand bridge → on-chain settlement verify → consensus pick. Second rail:
   blind-signed anonymous rate-limit tokens paid on Algorand.
4. **Architecture** — expert mixnet (Sphinx, Nitro-TEE matcher, reachability
   relay) + payment/honesty layer (x402, Algorand, EURD, blind-RSA, tiered
   honesty receipts).
5. **Demo / traction** — live network with real experts; 3 runnable demos;
   green test suite; real testnet ALGO payment unlocking an anonymous token.
6. **What's next** — EURD payouts to experts, threshold issuer, hard execution
   proofs; ask.

## Suggested demo video script (~4 min)
1. (30s) The problem + one-line pitch.
2. (60s) `python3 scripts/expert_pick_demo.py` — show the 402, the EURD
   `accepts` (asset 1221682136 on algorand:mainnet), the X-PAYMENT resubmit, and
   the reputation-weighted consensus pick excluding the flagged expert.
3. (60s) `python3 scripts/x402_algorand_demo.py` with a funded testnet account —
   show the real Algorand tx (lora.algokit.io link) unlocking a blind-signed
   anonymous token, then nullifier burn.
4. (45s) `python3 scripts/demo_phase1.py` — pay → issue → spend → honesty verify
   → double-spend blocked → attested (TEE) tier.
5. (30s) Show it riding the live expert network (config/live-enclave.json) and
   wrap with what's next.
</content>
</invoke>
