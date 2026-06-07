# tenet — pitch rubric (5–6 slides, ~5 min)

**Spine:** *A commerce agent that makes the right call when you'd rather not — and
pays real experts, over x402, to be sure.*

**Title:** **Outsource the decision, not the regret.**
**Tagline (under title):** A spend guardrail for autonomous agents — x402 · EURD · Algorand.

**Spoken opener (memorize this, it's the true story):**
> "I just booked an Airbnb and spent an hour second-guessing the neighborhood. I
> didn't want to be involved — I wanted it to be *right*. So I built an agent that
> pays a local to check, before it books."

Timing target: S1 ~40s · S2 ~40s · **S3 demo ~90s** · S4 ~60s · S5 ~45s · S6 ~30s.

---

## Slide 1 — The problem (hook)
**Headline:** Agents are starting to spend your money. Who do they trust?
- A bad call is expensive and irreversible — a wrecked trip, lost funds, the wrong vendor.
- The web's trust signals (reviews, SEO, 4.9★, affiliate links) are *curated to hide* the thing you need to know — and AI slop is making it worse, fast.
- A single model / Google can't tell you "is this the real neighborhood, or the edited-photos one?" Only a *local* can.
- **Show:** the opener line on screen; an Airbnb listing with a "4.9★" badge and a "?" over the neighborhood.

## Slide 2 — The solution
**Headline:** A spend guardrail: before the agent commits, it buys a verdict.
- Agent faces an expensive/irreversible choice → pays **a few cents of EURD over x402 on Algorand** → gets a tamper-resistant verdict on which option to choose.
- The verdict isn't one model's guess — it's **reputation- and stake-weighted consensus of independent experts** (here, locals who've walked the block).
- The payment is what makes it trustworthy: experts with **skin in the game**, not an answer you could've generated yourself.
- **Show:** the one-line loop — `options → 402 → pay EURD → expert consensus → verdict`.

## Slide 3 — Live demo (the 15-second loop)  ← run the site
**Headline:** Watch the agent book the right Airbnb.
- 3 Lisbon listings (the photogenic 4.9★ Alfama loft vs the quiet, safe Príncipe Real flat).
- `POST /pick` → **HTTP 402: pay €0.05 EURD** (asset `1221682136`, `algorand:mainnet`) → agent pays → verdict.
- Verdict = Príncipe Real, with reasoning, the experts who contributed, and the **on-chain EURD tx link**.
- **The bribe beat:** flip "Bribe attempt" — a host-paid promoter pushes the Alfama loft. It's *flagged & unstaked → weight 0 → excluded.* The verdict doesn't move.
- **Show:** the running site (`web/`). Real x402 + EURD wire shapes on screen at every step.
- **Say:** "The listing would never tell you the hills and 3am tuk-tuks ruin sleep. A local will. And the one expert who got paid to lie? Excluded — on screen."

## Slide 4 — Why it can't be gamed (the moat)
**Headline:** Trust = money, not vibes.
- **Un-gameable:** verdict is stake-weighted consensus. Corrupt one expert → nothing. To move it you must buy a stake-weighted majority — and a failed audit **slashes their EURD bond**. Bribery is negative-EV; sybils have zero stake → zero vote.
- **Private:** payment is **unlinkable** from the question (blind-signed tokens, RFC 9474). x402-as-usual sees everything; tenet doesn't.
- **Verifiable:** every answer carries a nonce-bound receipt the asker checks offline — proof the expert did the work (opt-in hard TEE tier).
- **Show:** the bribe math (cost-to-attack > stake-at-risk + lost earnings) and the three pillars.

## Slide 5 — How it uses x402 + Algorand + EURD
**Headline:** The payment is the mechanism, not a bolt-on.
- **x402:** the `402 → X-PAYMENT → verify` handshake *is* the product gate. No payment, no verdict.
- **EURD (Quantoz):** settled in a MiCA-compliant euro stablecoin over the EURO→Algorand bridge to a whitelisted address; merchant confirms the EURD landed **on-chain** (indexer, replay-guarded). *(Quantoz bonus track.)*
- **Algorand:** fast, cheap, final — the rail that makes few-cent agentic payments actually work.
- **Built during the hackathon** on top of an already-live expert-routing network (Sphinx mixnet + Nitro-TEE matcher). Code: `tenet/x402.py`, `tenet/quantoz.py`, `tenet/algorand.py`, `tenet/expert_pick.py`.

## Slide 6 — Traction & ask
**Headline:** Live today; here's what's next.
- Live expert network with real experts; **3 runnable demos**; green test suite; a real Algorand testnet payment unlocking an anonymous token.
- **Next:** on-chain EURD staking/slashing escrow + expert payouts; decentralized audit/dispute; more verticals (DeFi, procurement) — same primitive.
- **Ask:** [partners / pilot / prize] — we want agents everywhere to consult tenet before they spend.
- **Close (callback):** "Outsource the decision. Keep the trip."

---

### Slide-making notes
- 6 slides max, ~10 words per bullet, one idea per slide. Let the **demo** carry slide 3 — don't read bullets over it.
- Put the **on-chain tx link** on screen during the demo; judges want to see the chain.
- Lead with the human story (S1), prove it live (S3), then justify the mechanism (S4–5). Don't open with architecture.
- If you only get 2 minutes: opener → run the loop → bribe beat → "x402 + EURD on Algorand, live." Done.
</content>
