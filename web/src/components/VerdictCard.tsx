import type { ConsensusResponse, Scenario } from "../lib/types";
import type { PickSource } from "../lib/pickClient";

export default function VerdictCard({
  scenario,
  verdict,
  source,
}: {
  scenario: Scenario;
  verdict: ConsensusResponse;
  source: PickSource;
}) {
  const opt = (id: string) => scenario.options.find((o) => o.id === id);
  const picked = opt(verdict.pick_id);
  const winningPick = verdict.picks.find(
    (p) => p.expert_id === verdict.contributing_experts[0],
  );

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line bg-good/5 px-5 py-3">
        <span className="text-sm font-semibold text-good">VERDICT</span>
        <span
          className={`chip ${
            source === "live"
              ? "border-good/50 text-good"
              : "border-accent2/50 text-accent2"
          }`}
        >
          {source === "live" ? "● LIVE PickServer" : "● Simulated (real shapes)"}
        </span>
      </div>

      <div className="p-5">
        <div className="text-xs uppercase tracking-wide text-mute">
          Book this one
        </div>
        <div className="mt-1 text-2xl font-bold">{picked?.label}</div>
        <div className="mt-1 text-sm text-mute">{picked?.meta}</div>
        <p className="mt-3 text-sm text-fg/90">
          {winningPick?.reasoning}
        </p>

        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          <Stat
            label="Consensus"
            value={`${Math.round(verdict.agreement * 100)}%`}
            sub="of staked weight"
          />
          <Stat
            label="Contributed"
            value={String(verdict.contributing_experts.length)}
            sub="staked experts"
          />
          <Stat
            label="Excluded"
            value={String(verdict.excluded_experts.length)}
            sub="flagged / unstaked"
            danger
          />
        </div>

        <div className="mt-5">
          <div className="text-xs font-semibold text-mute">
            Ranking (weighted Borda)
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            {verdict.ranking.map((id, i) => (
              <span key={id} className="flex items-center gap-2">
                <span
                  className={`rounded-lg border px-2.5 py-1 ${
                    i === 0
                      ? "border-good/50 bg-good/10 text-good"
                      : "border-line bg-panel2 text-mute"
                  }`}
                >
                  {opt(id)?.label ?? id}
                </span>
                {i < verdict.ranking.length - 1 && (
                  <span className="text-mute">›</span>
                )}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-5 rounded-xl border border-line bg-ink/60 p-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-mute">Paid by agent</span>
            <span className="mono">{verdict.payer ?? "agent-wallet"}</span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-mute">EURD settlement</span>
            <a
              className="mono text-accent hover:underline"
              href={scenario.explorerTxBase + verdict.tx}
              target="_blank"
              rel="noreferrer"
            >
              {verdict.tx} ↗
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  danger,
}: {
  label: string;
  value: string;
  sub: string;
  danger?: boolean;
}) {
  return (
    <div className="rounded-xl border border-line bg-panel2 p-3">
      <div className="text-xs text-mute">{label}</div>
      <div className={`mt-1 text-xl font-bold ${danger ? "text-danger" : ""}`}>
        {value}
      </div>
      <div className="text-[11px] text-mute">{sub}</div>
    </div>
  );
}
