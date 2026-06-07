export default function Hero() {
  return (
    <header className="mx-auto max-w-6xl px-5 pt-16 pb-8 sm:pt-24">
      <div className="flex items-center gap-2">
        <span className="text-lg font-bold tracking-tight">tenet</span>
        <span className="chip">x402 · EURD · Algorand</span>
      </div>

      <h1 className="mt-8 max-w-3xl text-4xl font-bold leading-[1.05] tracking-tight sm:text-6xl">
        Outsource the decision,
        <br />
        <span className="text-accent">not the regret.</span>
      </h1>

      <p className="mt-6 max-w-2xl text-lg text-mute">
        A commerce agent that makes the right call when you'd rather not — and
        pays real experts, over x402, to be sure. Before it commits to something
        expensive or irreversible, it spends a few cents of EURD on Algorand for
        a tamper-resistant verdict on which option to choose.
      </p>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <a href="#loop" className="btn-primary">
          See the 15-second loop ↓
        </a>
        <a
          href="https://github.com/maceip/sphinx-tahoe"
          target="_blank"
          rel="noreferrer"
          className="btn-ghost"
        >
          GitHub
        </a>
      </div>

      <p className="mt-8 max-w-2xl border-l-2 border-line pl-4 text-sm italic text-mute">
        “I just booked an Airbnb and spent an hour second-guessing the
        neighborhood. I didn't want to be involved — I wanted it to be right. So
        I built an agent that pays a local to check, before it books.”
      </p>
    </header>
  );
}
