import type { ConsensusResponse, Scenario } from "../lib/types";

export default function ExpertPanel({
  scenario,
  verdict,
  bribed,
}: {
  scenario: Scenario;
  verdict: ConsensusResponse | null;
  bribed: boolean;
}) {
  const optionLabel = (id: string) =>
    scenario.options.find((o) => o.id === id)?.label ?? id;

  const isExcluded = (id: string) =>
    verdict ? verdict.excluded_experts.includes(id) : false;

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-mute">
          The quorum · weight = staked EURD
        </h3>
        <span className="chip">{scenario.experts.length} experts</span>
      </div>

      <ul className="mt-4 space-y-3">
        {scenario.experts.map((e) => {
          const excluded = e.flagged || isExcluded(e.id);
          const isShill = bribed && e.id === "promo-host";
          return (
            <li
              key={e.id}
              className={`rounded-xl border p-4 transition ${
                excluded
                  ? "border-danger/40 bg-danger/5"
                  : "border-line bg-panel2"
              } ${isShill ? "ring-1 ring-danger/60" : ""}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-semibold">{e.label}</div>
                  <div className="mt-0.5 text-xs text-mute">{e.bio}</div>
                </div>
                <div className="text-right">
                  <div
                    className={`mono ${
                      excluded ? "text-danger line-through" : "text-accent"
                    }`}
                  >
                    €{e.stakeEurd} staked
                  </div>
                  <div className="mt-0.5 text-[11px] text-mute">
                    picks {optionLabel(e.pick)}
                  </div>
                </div>
              </div>

              {e.disclosures.some((d) => d !== "none") && (
                <div className="mt-2 text-xs text-warn">
                  ⚠ discloses: {e.disclosures.join("; ")}
                </div>
              )}

              {excluded && (
                <div className="mt-2 inline-flex rounded-md bg-danger/15 px-2 py-0.5 text-[11px] font-semibold text-danger">
                  EXCLUDED — {e.flagged ? "flagged / unstaked → weight 0" : "zero weight"}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <p className="mt-4 text-xs text-mute">
        To bias the verdict you'd have to corrupt a stake-weighted majority — and
        a failed audit slashes their bond. Bribery is negative-EV; sybils have
        zero stake, so zero vote.
      </p>
    </div>
  );
}
