# tenet — demo site

Front-end for **tenet**: a spend guardrail for autonomous agents. Before an agent
commits to an expensive or irreversible action, it pays a few cents of **EURD over
x402 on Algorand** for a tamper-resistant, reputation-/stake-weighted expert
verdict on which option to choose.

This is the pitch/demo surface. The verdict is produced by the real Python
`PickServer` (`tenet/pick_server.py`) when one is reachable; otherwise the UI
falls back to a faithful client-side simulation that uses the **same wire shapes**
(x402 `accepts`, the EURD bridge proof, and the reputation/stake-weighted
consensus response) so the demo never fails on stage.

## Stack
Vite + React + TypeScript + Tailwind. Static build — host anywhere
(Vercel / Netlify / Cloudflare / GitHub Pages).

## Run
```bash
cd web
npm install
npm run dev        # http://localhost:5173
```

## Wire to the real PickServer
The UI POSTs to `/pick`. In dev, Vite proxies `/pick` to your PickServer.

1. Start the backend (example):
   ```bash
   # from repo root — see scripts/expert_pick_demo.py for a runnable server
   ANTHROPIC_API_KEY=... python3 scripts/expert_pick_demo.py
   ```
2. Point the proxy at it:
   ```bash
   echo 'VITE_PICK_SERVER_URL=http://127.0.0.1:PORT' > web/.env.local
   ```
   (The demo script prints its `server:` URL.)

If `VITE_PICK_SERVER_URL` is unset or the call fails, the UI uses the built-in
simulation. A small badge in the UI shows **LIVE** vs **SIMULATED** so you always
know which path produced the verdict.

> Browser → Python `PickServer` needs CORS; the Vite dev proxy handles it in dev.
> For a hosted demo, put the PickServer behind a proxy that adds CORS, or keep the
> simulated path.

## The 15-second demo beat
agent has 3 options → `POST /pick` → **402: pay €0.05 EURD on Algorand** → agent
pays → ranked verdict + reasoning + which experts contributed / which were
excluded (flagged or unstaked) + the on-chain tx link. One screen, full loop.

## Swap the scenario
Everything on screen is driven by `src/data/scenario.ts` — change the agent, the
decision, the options, and the experts (stake, weight, pick, disclosures, flagged)
in one file.
