export default function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto max-w-6xl px-5 py-10 text-sm text-mute">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="font-semibold text-fg">tenet</div>
            <div className="mt-1">
              A spend guardrail for autonomous agents · x402 · EURD · Algorand
            </div>
          </div>
          <div className="flex gap-5">
            <a
              className="hover:text-accent"
              href="https://github.com/maceip/sphinx-tahoe"
              target="_blank"
              rel="noreferrer"
            >
              GitHub
            </a>
            <a className="hover:text-accent" href="#loop">
              Demo
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
