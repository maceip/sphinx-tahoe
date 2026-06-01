# Enclave Plane on run-cards — Deployment & Trust Runbook

How the (plain, today) enclave-plane service becomes the **hardened, attested**
central plane from `docs/matcher_threat_model.md`, by recycling the run-cards TEE
engine (`/Users/mac/runcards`) instead of writing new enclave code.

Status: **integration designed; client gate built + tested; hardware bring-up
pending.** No matcher/mailbox Rust rewrite is required.

## The recycle

run-cards already provides, hardware-proven on AWS Nitro, AMD SEV-SNP, and Intel
TDX:

- **Attested runtime (Stage 1):** runs an arbitrary workload inside a TEE and
  fronts it with **attested TLS** (the TLS cert carries an EAT bound to the
  hardware quote and to `sha256(cert_spki)`).
- **`runcard check <url>`** (src/main.rs `cmd_check`): quote signature chain →
  `report_data` binding → `sha256(cert_spki) == eat.tls_spki_hash` channel
  binding → Value X registry lookup.
- Receipt served at `GET /.well-known/runcard/receipt`.
- "Bootstrap once, then cheap" trust pattern (DESIGN.md / LLM_ATTESTED.md).

run-cards' own guidance: *do not modify the core quote verifier; build on top of
attested TLS; reuse EAT + quote verification as-is.* We follow it exactly.

## Server side — the matcher/mailbox runs *as the workload*

The existing `por.enclave_plane` HTTP service (matcher + mailbox, `/v1/match`,
`/v1/routing-key`, `/v1/relay-path`, `/v1/deliver`) runs **inside** the enclave
as the run-cards Stage-1 workload, bound to loopback. run-cards terminates
attested TLS in front of it and bridges vsock → loopback. The Python stays
Python; the TEE wrapper is run-cards.

```
verifier ── attested TLS:443 ──▶ [run-cards Stage 1, in TEE]
                                   ├─ EAT in cert, /.well-known/runcard/receipt
                                   └─ vsock → 127.0.0.1:<port> ──▶ por.enclave_plane (matcher+mailbox)
```

Outstanding to make this runnable:
- A standalone entry point that builds `PlainMatcher` + `PlainMailbox` +
  `PlainEnclavePlaneDiscoveryProvider` and serves
  `make_plain_enclave_plane_handler` on a configurable loopback bind. (Next task.)
- Stage-0 build of that entry point → a Value X to approve in the registry.

## Client side — the attestation gate (built: `por/enclave_attest.py`)

`AttestedEnclavePlaneClient` wraps any enclave-plane client and **gates every
call on attestation**, failing closed:

1. On first use, `RuncardVerifier.verify(base_url)` runs the run-cards crypto
   (delegated — `SubprocessRuncardVerifier` shells out to `runcard check`).
2. `EnclaveTrustPolicy.evaluate(...)` applies the sphinx-tahoe-owned policy:
   approved Value X set, accepted TEE platforms, accepted registry status. An
   empty approved set rejects everything (fail closed).
3. On success the verified attestation is cached (bootstrap-once); on any
   failure it raises `EnclaveAttestationError` and **never** calls the inner
   client — no silent downgrade to an unattested transport (invariant I1).

```python
client = AttestedEnclavePlaneClient(
    PlainEnclavePlaneHttpClient("https://matcher.example"),
    verifier=SubprocessRuncardVerifier(),          # delegates to `runcard check`
    policy=EnclaveTrustPolicy(
        approved_value_x=frozenset({"<sha384 of the approved matcher build>"}),
        accepted_platforms=frozenset({"nitro", "sev-snp", "tdx"}),
    ),
)
client.discover(request)   # only runs if attestation + policy pass
```

## Remaining hardening items (tracked)

1. **Server entry point** to run matcher/mailbox as the Stage-1 workload.
2. **`SubprocessRuncardVerifier` field extraction** — `runcard check` proves the
   crypto via exit code; pulling `value_x` / `platform` for policy currently
   parses `/.well-known/runcard/receipt` defensively. Validate the receipt JSON
   schema against a live enclave (or add `runcard check --json`).
3. **SPKI pin enforcement** — once the transport is real TLS (not the plain HTTP
   stand-in), pin `pinned_spki` on subsequent connections.
4. **Oblivious algorithms** inside the workload (ORAM / oblivious sort) — the TEE
   stops the operator reading content; obliviousness stops it inferring from
   access patterns. This is the deepest box and is still ahead.
5. **Hardware bring-up** — Stage-0 build → Value X → approve in registry →
   Stage-1 run on a Nitro/SNP/TDX instance → `runcard check` from the client.
