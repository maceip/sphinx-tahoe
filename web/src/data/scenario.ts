import type { Scenario } from "../lib/types";

// ── Swap this file to change the entire demo ──────────────────────────────────
// The story: a booking agent must pick an Airbnb for you. A listing will never
// tell you which neighborhood actually sleeps quiet / is safe at night. So the
// agent pays €0.05 EURD over x402 on Algorand for a verdict from staked local
// experts — and a host-paid shill pushing the photogenic-but-wrong listing is
// excluded from the quorum.
//
// EURD ASA on Algorand mainnet = 1221682136 (tenet/quantoz.py: EURD_ASA_MAINNET).
// EURD has 2 decimals: priceAtomic 5 = €0.05.

export const scenario: Scenario = {
  agentName: "Concierge agent",
  decisionTitle: "Book 4 nights in Lisbon",
  decisionContext:
    "Two adults · €140/night budget · wants walkable + safe at night · near nightlife but quiet to actually sleep.",
  question:
    "Booking 4 nights in Lisbon for two adults. Walkable and safe at night, close to nightlife but quiet enough to sleep. Which listing should I book?",

  network: "algorand:mainnet",
  asset: "1221682136",
  assetLabel: "EURD",
  priceAtomic: 5,
  priceLabel: "€0.05",
  payTo: "TENETPOOLXATTESTEDMERCHANTWHITELISTEDALGOADDRESS7Q",
  explorerTxBase: "https://lora.algokit.io/mainnet/tx/",

  options: [
    {
      id: "l1",
      label: "Alfama · “Charming Loft”",
      detail:
        "Photogenic, postcard views. Steep hills, tourist-packed, tuk-tuks past 2am.",
      meta: "4.9★ (212) · €128/night",
      tag: "Most reviews",
    },
    {
      id: "l2",
      label: "Príncipe Real · 1-BR",
      detail:
        "Leafy, central, quiet residential street. 8-min walk to Bairro Alto nightlife.",
      meta: "4.7★ (88) · €139/night",
      tag: "Best fit",
    },
    {
      id: "l3",
      label: "Intendente · “Designer Studio”",
      detail:
        "Trendiest strip, great food. Lively/edgy at night, rowdy on weekends.",
      meta: "4.95★ (40) · €99/night",
      tag: "Cheapest",
    },
  ],

  experts: [
    {
      id: "local-ana",
      label: "Ana — Lisbon resident (Graça)",
      bio: "Lives 10 min away. Knows which streets go quiet after midnight.",
      stakeEurd: 250,
      flagged: false,
      pick: "l2",
      ranking: ["l2", "l1", "l3"],
      reasoning:
        "Príncipe Real is a quiet leafy street — you'll actually sleep — and it's a short safe walk to nightlife. Alfama is beautiful but the hills and late tuk-tuks wreck your nights.",
      confidence: 0.86,
      disclosures: ["none"],
    },
    {
      id: "local-rui",
      label: "Rui — ex-tour guide",
      bio: "Walked these neighborhoods for a living for 6 years.",
      stakeEurd: 180,
      flagged: false,
      pick: "l2",
      ranking: ["l2", "l3", "l1"],
      reasoning:
        "Alfama looks best in photos and hides 3am noise; Intendente is fun but rough on weekends. Príncipe Real balances safe + central + quiet.",
      confidence: 0.81,
      disclosures: ["none"],
    },
    {
      id: "local-maria",
      label: "Maria — food writer",
      bio: "Reviews restaurants across the city; biased toward the lively bits.",
      stakeEurd: 120,
      flagged: false,
      pick: "l3",
      ranking: ["l3", "l2", "l1"],
      reasoning:
        "Intendente has the best food and energy and it's the cheapest — but I'll admit it's loud on Fri/Sat.",
      confidence: 0.7,
      disclosures: ["none"],
    },
    {
      id: "promo-host",
      label: "“TopStays” promoter",
      bio: "Recommends the most photogenic, highest-review listing.",
      stakeEurd: 0,
      flagged: true,
      pick: "l1",
      ranking: ["l1", "l3", "l2"],
      reasoning:
        "Alfama Charming Loft has the most reviews and the best photos — book it!",
      confidence: 0.95,
      disclosures: ["compensated by the host (Superhost partner program)"],
    },
  ],
};

// A relatable on-stage bribe: the host wires EURD to flip the verdict to their listing.
export const bribe = {
  expertId: "promo-host",
  amountLabel: "€50",
  targetOption: "l1",
  note: "Host pays the promoter €50 to recommend the Alfama loft.",
};
