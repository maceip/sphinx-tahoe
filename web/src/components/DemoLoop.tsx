import { useState } from "react";
import type { ConsensusResponse, Scenario } from "../lib/types";
import {
  buildBridgeProof,
  challengeBody,
  fakeTxCode,
  fetchVerdict,
  type PickSource,
} from "../lib/pickClient";
import { bribe } from "../data/scenario";
import ExpertPanel from "./ExpertPanel";
import VerdictCard from "./VerdictCard";

type Phase = "idle" | "request" | "challenge" | "paying" | "verifying" | "done";

const STEPS: { key: Phase; label: string }[] = [
  { key: "request", label: "Agent asks" },
  { key: "challenge", label: "402: pay €0.05 EURD" },
  { key: "paying", label: "Pay on Algorand" },
  { key: "verifying", label: "Verify on-chain" },
  { key: "done", label: "Verdict" },
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function DemoLoop({ scenario }: { scenario: Scenario }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [running, setRunning] = useState(false);
  const [verdict, setVerdict] = useState<ConsensusResponse | null>(null);
  const [source, setSource] = useState<PickSource>("simulated");
  const [tx, setTx] = useState<string>("");
  const [bribed, setBribed] = useState(false);

  async function run() {
    setRunning(true);
    setVerdict(null);
    setPhase("request");
    await sleep(800);
    setPhase("challenge");
    await sleep(1100);
    setPhase("paying");
    const txCode = fakeTxCode();
    setTx(txCode);
    await sleep(1100);
    setPhase("verifying");
    const proof = buildBridgeProof(scenario, txCode);
    const { verdict: v, source: src } = await fetchVerdict(
      scenario,
      proof,
      "AGENT_WALLET_" + txCode.slice(3, 9),
      txCode,
    );
    await sleep(700);
    setVerdict(v);
    setSource(src);
    setPhase("done");
    setRunning(false);
  }

  function reset() {
    setPhase("idle");
    setVerdict(null);
    setRunning(false);
  }

  const stepIndex = STEPS.findIndex((s) => s.key === phase);

  return (
    <section id="loop" className="mx-auto max-w-6xl px-5 py-12">
      <div className="card p-6 sm:p-8">
        {/* decision header */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <span className="chip">{scenario.agentName}</span>
            <h2 className="mt-3 text-2xl font-bold tracking-tight">
              {scenario.decisionTitle}
            </h2>
            <p className="mt-1 max-w-xl text-sm text-mute">
              {scenario.decisionContext}
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={run} disabled={running} className="btn-primary">
              {running ? "Running…" : phase === "done" ? "Run again" : "Run the loop"}
            </button>
            {phase !== "idle" && (
              <button onClick={reset} className="btn-ghost">
                Reset
              </button>
            )}
          </div>
        </div>

        {/* stepper */}
        <ol className="mt-7 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {STEPS.map((s, i) => {
            const active = i === stepIndex;
            const done = stepIndex > i || phase === "done";
            return (
              <li
                key={s.key}
                className={`rounded-xl border px-3 py-2 text-xs font-medium ${
                  active
                    ? "border-accent/60 bg-accent/10 text-accent animate-pulseline"
                    : done
                      ? "border-good/40 bg-good/5 text-good"
                      : "border-line bg-panel2 text-mute"
                }`}
              >
                <span className="mr-1.5 opacity-60">{i + 1}</span>
                {s.label}
              </li>
            );
          })}
        </ol>

        <div className="mt-7 grid gap-5 lg:grid-cols-2">
          {/* left: options + live wire */}
          <div className="space-y-4">
            <div className="card p-5">
              <h3 className="text-sm font-semibold text-mute">
                The agent's 3 options
              </h3>
              <ul className="mt-3 space-y-2">
                {scenario.options.map((o) => {
                  const win = verdict?.pick_id === o.id;
                  return (
                    <li
                      key={o.id}
                      className={`rounded-xl border p-3 transition ${
                        win
                          ? "border-good/50 bg-good/10"
                          : "border-line bg-panel2"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold">{o.label}</span>
                        <span className="chip">{o.tag}</span>
                      </div>
                      <div className="mt-1 text-xs text-mute">{o.meta}</div>
                      <div className="mt-1 text-xs text-mute/80">{o.detail}</div>
                    </li>
                  );
                })}
              </ul>
            </div>

            <WirePanel scenario={scenario} phase={phase} tx={tx} />
          </div>

          {/* right: experts, then verdict */}
          <div className="space-y-4">
            <ExpertPanel
              scenario={scenario}
              verdict={verdict}
              bribed={bribed}
            />

            {/* bribe beat */}
            <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-danger/30 bg-danger/5 p-4 text-sm">
              <input
                type="checkbox"
                checked={bribed}
                onChange={(e) => setBribed(e.target.checked)}
                className="h-4 w-4 accent-danger"
              />
              <span>
                <span className="font-semibold text-danger">
                  Bribe attempt:
                </span>{" "}
                {bribe.note} The promoter is flagged &amp; unstaked → weight 0,
                so the verdict doesn't move.
              </span>
            </label>

            {verdict && (
              <VerdictCard
                scenario={scenario}
                verdict={verdict}
                source={source}
              />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function WirePanel({
  scenario,
  phase,
  tx,
}: {
  scenario: Scenario;
  phase: Phase;
  tx: string;
}) {
  let title = "Protocol — real wire shapes";
  let body = "Press “Run the loop”. This panel shows the actual x402 + EURD payload at each step.";

  if (phase === "request") {
    body = `POST /pick\n{\n  "question": "${scenario.question.slice(0, 48)}…",\n  "options": [ l1, l2, l3 ]\n}`;
  } else if (phase === "challenge") {
    title = "← HTTP 402 Payment Required";
    body = JSON.stringify(challengeBody(scenario), null, 2);
  } else if (phase === "paying") {
    title = "Paying EURD on Algorand…";
    body = `EURO → EURD bridge (Quantoz)\nasset ${scenario.asset} (${scenario.assetLabel})\namount ${scenario.priceAtomic} atomic = ${scenario.priceLabel}\nto ${scenario.payTo.slice(0, 20)}…\ntxCode ${tx || "…"}`;
  } else if (phase === "verifying") {
    title = "→ resubmit with X-PAYMENT";
    body = `X-PAYMENT: ${buildBridgeProof(scenario, tx).slice(0, 64)}…\n\nmerchant verifies the EURD landed on-chain\n(indexer watch on payTo, replay-guarded)`;
  } else if (phase === "done") {
    title = "✓ settled — verdict returned";
    body = `EURD confirmed on Algorand\ntx ${tx}\n${scenario.explorerTxBase}${tx}`;
  }

  return (
    <div className="card p-5">
      <h3 className="text-sm font-semibold text-mute">{title}</h3>
      <pre className="codeblock mt-3 min-h-[150px] text-[11.5px]">{body}</pre>
    </div>
  );
}
