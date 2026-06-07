const pillars = [
  {
    name: "Un-gameable",
    color: "text-accent",
    body: "The verdict is reputation- and stake-weighted consensus of independent experts. One can be bribed; a staked quorum can't — and a paid shill is excluded, on screen.",
    code: "tenet/expert_pick.py",
  },
  {
    name: "Private",
    color: "text-accent2",
    body: "Payment is unlinkable from the request. The agent pays over x402 with blind-signed tokens — the network can't tie what you asked to what you paid.",
    code: "tenet/blind_rsa.py",
  },
  {
    name: "Verifiable",
    color: "text-good",
    body: "Every answer carries a nonce-bound receipt the asker checks offline — proof the expert actually did the work, with an opt-in hard TEE tier.",
    code: "tenet/honesty.py",
  },
];

export default function Pillars() {
  return (
    <section className="mx-auto max-w-6xl px-5 py-16">
      <h2 className="text-2xl font-bold tracking-tight">
        Why an agent can trust it
      </h2>
      <p className="mt-2 max-w-2xl text-mute">
        As agents start spending money, the web's trust signals (reviews, SEO,
        affiliate links) collapse into manipulable slop. tenet is the trust layer
        underneath agentic commerce.
      </p>
      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {pillars.map((p) => (
          <div key={p.name} className="card p-6">
            <h3 className={`text-lg font-semibold ${p.color}`}>{p.name}</h3>
            <p className="mt-2 text-sm text-mute">{p.body}</p>
            <code className="mono mt-4 block text-mute/70">{p.code}</code>
          </div>
        ))}
      </div>
    </section>
  );
}
