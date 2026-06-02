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
- **`runcard check <url>`** (src/main.rs `cmd_check`): opens attested TLS, pulls
  the EAT (**CBOR, embedded in the leaf cert's CMW extension** — not a JSON
  document), checks `sha256(cert_spki) == eat.tls_spki_hash` channel binding →
  quote signature + `report_data` binding → stage-chain walk (Value X stable).
  Exit 0 = all passed; `Value X` / `Platform` printed to stderr (and as one JSON
  line on stdout under `--json`).
- A CBOR receipt at `GET /.well-known/runcard/receipt` exists, but it is served
  by runcards' **`llm-gateway`** binary (`src/bin/llm-gateway.rs:260`), not by the
  generic Stage-1 wrapper. Our channel binding does **not** depend on it: the EAT
  the verifier needs is in the leaf cert, fetched during the TLS handshake.
- **Verified locally, no TEE:** runcards `chain_e2e` 5/5 and the Nitro/TDX
  `hardware_regression` fixtures pass on a plain Mac; only SNP (AMD KDS) and
  *fresh-quote generation* need a live instance.
- "Bootstrap once, then cheap" trust pattern (DESIGN.md / LLM_ATTESTED.md).

run-cards' own guidance: *do not modify the core quote verifier; build on top of
attested TLS; reuse EAT + quote verification as-is.* We follow it exactly.

## Server side — the matcher/mailbox runs *as the workload*

The existing `por.enclave_plane` HTTP service (matcher + mailbox, `/v1/match`,
`/v1/routing-key`, `/v1/relay-path`, `/v1/deliver`) runs **inside** the enclave
as the run-cards Stage-1 workload, bound to loopback. The Python stays Python;
the TEE wrapper is run-cards.

**Where TLS terminates is load-bearing, and it differs by platform.** The cert's
SPKI is what the EAT binds to (`sha256(cert_spki) == eat.tls_spki_hash`), so the
TLS private key **must** live inside the TEE — otherwise the channel binding
proves nothing.

*Nitro (enclave model — `bountynet-genesis/v2`):* the enclave has no network
stack of its own, only a vsock to the parent. So the parent runs a **dumb
TCP:443 → vsock byte bridge** and **TLS terminates inside the enclave**, not at
the parent. Source, verbatim: *"The enclave terminates TLS — the parent only sees
encrypted traffic"* (`v2/src/main.rs:97`); *"TLS terminates INSIDE the enclave.
The host never sees plaintext"* (`v2/src/net/vsock.rs:3`). The parent's `--acme`
only provisions the Let's Encrypt cert (TLS-ALPN-01); the key and rustls
termination are enclave-side (`v2/STAGES.md:152`, `v2/src/net/acme.rs:25`).

```
verifier ── attested TLS:443 ──▶ [parent: bountynet proxy, raw TCP→vsock bridge, sees only ciphertext]
                                          │ vsock
                                          ▼
                                 [Nitro enclave, in TEE]
                                   ├─ rustls TLS termination  (key is TEE-resident → SPKI binds)
                                   ├─ EAT in leaf cert (CMW ext, CBOR)
                                   └─ 127.0.0.1:<port> ──▶ por.enclave_plane (matcher+mailbox)
```

*SEV-SNP (Azure CVM) / TDX (GCP) — whole-VM model:* the entire VM is the TEE and
has a normal network stack, so there is **no vsock bridge** — attested TLS
terminates directly in the confidential VM and the matcher/mailbox runs as a
local process beside it. Same channel-binding guarantee, simpler topology;
the Nitro vsock hop is the price Nitro charges for being an isolated enclave
rather than a confidential VM. (`deploy/azure-cvm.sh`, `deploy/gcp-tdx.sh`.)

Built:
- `por/enclave_plane_server.py` — `python3 -m por.enclave_plane_server
  --snapshot <public snapshot> --mailbox <private resolution file>` builds the
  matcher (from the public snapshot) + mailbox (from a private file the enclave
  holds, since handle→reachability is not public by #4) and serves the handler
  on a loopback bind. Verified over HTTP in `tests/test_enclave_plane_server.py`.

Outstanding:
- Stage-0 build of that entry point → a Value X to approve in the registry.

### Nitro deploy path (recovered from `bountynet-genesis/v2/BUILD.md`)

The Nitro deploy is **not** a single committed script — it is the EIF + nitro-cli
+ parent-proxy sequence below (this is why it never showed up as a `deploy/*.sh`
like the SNP/TDX sisters):

```bash
# Provision a Nitro-capable instance
aws ec2 run-instances --instance-type m5.xlarge \
  --image-id ami-<nitro-enabled> --enclave-options 'Enabled=true'
sudo amazon-linux-extras install aws-nitro-enclaves-cli -y
sudo systemctl enable --now nitro-enclaves-allocator

# Build the EIF (reproducible → PCR0); our matcher entry point is the workload
docker build -t nodea -f Dockerfile.enclave .          # amazonlinux:2023 base
nitro-cli build-enclave --docker-uri nodea:latest --output-file nodea.eif

# Run the enclave + parent-side vsock bridge with ACME TLS
sudo nitro-cli run-enclave --cpu-count 2 --memory 3500 --eif-path nodea.eif
CID=$(nitro-cli describe-enclaves | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['EnclaveCID'])")
bountynet proxy --cid $CID --port 443 --acme           # TCP:443 → vsock; TLS terminates in-enclave
```

For our use: the matcher/mailbox entry point becomes the EIF workload
(`Dockerfile.enclave`), Stage-0 attested-builds it → PCR0/Value X, and the parent
runs `bountynet proxy`. The client then `runcard check`s the public endpoint and
the gate in `por/enclave_attest.py` approves that Value X.

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

1. ~~Server entry point to run matcher/mailbox as the Stage-1 workload.~~
   **Built:** `por/enclave_plane_server.py`.
2. ~~**`SubprocessRuncardVerifier` output parsing** — add a `runcard check
   --json` mode so policy fields come from structured stdout, not brittle stderr
   scraping.~~ **Done:** `--json` shipped in runcards (`runcard.check.v1`); the
   verifier prefers it and falls back to stderr for older binaries (commit
   `31e00cf`). (The EAT is CBOR in the TLS cert's CMW extension, not a JSON
   receipt — corrected from the first cut.)
3. ~~**SPKI pin enforcement** — once the transport is real TLS, pin
   `pinned_spki` on subsequent connections.~~ **Done.** `runcard check --json`
   now emits `tls_spki_hash` (the SPKI it bound the EAT to; runcards
   `src/main.rs` cmd_check). The verifier carries it into the attestation;
   `AttestedEnclavePlaneClient.establish()` pins the inner transport to it
   (`por/attested_transport.py` `build_pinned_opener` — no CA chain, SPKI is the
   sole authenticator, matching runcards' `NoVerify`). A mismatch raises
   `SpkiPinError` (fail-closed). `EnclaveTrustPolicy(require_spki_pin=True)`
   refuses to proceed unpinned. Proven end-to-end against a live self-signed
   HTTPS server in `tests/test_attested_transport.py`; pinning a plaintext
   `http://` transport is refused, not silently skipped.
4. **Oblivious algorithms** inside the workload — the TEE stops the operator
   reading content; obliviousness stops it inferring from access patterns.
   Status, stated precisely so the remaining work is not overclaimed:
   - **Done (security property):** matcher selection and mailbox resolution both
     run as a *uniform full scan* (`por/oblivious.py`, `PlainMailbox.resolve_handle`)
     — the access trace is byte-identical regardless of which expert/handle was
     the target (proven in `tests/test_oblivious*.py`). For a top-K over N
     experts a full scan is not just oblivious but optimal: you must touch all N
     or you leak which you skipped.
   - **Done (security property):** the output *count* is hidden — the response is
     always exactly K, empty slots padded with cover handles (`por/cover.py`,
     `tests/test_cover_handles.py`); the asker drops covers, the operator cannot.
   - **Done (constant-time port):** `oblivious-core/` is a Rust crate that ports
     the selection to branchless `subtle` conditional selects (CMOV-level), so
     the branch/timing trace is data-independent, not just the access order.
     Tested + verified byte-for-byte identical to `por/oblivious.py`. **Remaining
     integration:** the live enclave matcher still calls the Python version;
     wiring the crate in (PyO3 or a Rust selection step) is the next step.
   - **Deferred (performance, not security):** ORAM / oblivious sort would make
     resolution sublinear, but they do **not** improve obliviousness over the
     full scan — they are a scale optimization, not a security gap.
5. **Hardware bring-up** — Stage-0 build → Value X → approve in registry →
   Stage-1 run on a Nitro/SNP/TDX instance → `runcard check` from the client.
   - **Done (no hardware needed):** the EIF packaging (`deploy/Dockerfile.enclave`
     + workload/entry scripts) and the recovered Nitro deploy sequence
     (`deploy/nitro-deploy.sh`, provision → build EIF → run-enclave → parent vsock
     proxy), plus the PCR0→Value X→`EnclaveTrustPolicy` wiring. runcards'
     *verification* runs green locally (`chain_e2e`, Nitro/TDX `hardware_regression`).
   - **Genuinely hardware-gated:** *fresh-quote generation* — only obtainable
     inside a live enclave (NSM / `/dev/sev-guest` / configfs-tsm). Verification
     works locally; generation does not.
   - **Integration gap (tracked):** bountynet serves the EAT/attestation over the
     enclave vsock-TLS but does **not** yet reverse-proxy the matcher API onto
     that attested channel (`serve_tls_vsock` serves attestation, not an app).
     The matcher's `/v1/*` is therefore not yet reachable over attested TLS. See
     `deploy/README.md` and the bountynet app-proxy task.
