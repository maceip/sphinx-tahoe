# Proof of execution (zkTLS / TLSNotary prover)

Locked decisions: **`docs/por_locked_decisions.md`**.

Execution proof is **base `por.app.v1` behavior**, not a relay extension and not
negotiated via `client_extensions`.

## Composition (front end + prover)

```text
client + expert already online (2P)
    → mpc_session on request binds verifier_peer_id
expert HTTP call (anthropic | openai)  [expert = MPC prover]
    → execution_trace on final done frame     ← wire front end (por/execution.py)
        → proof_obligation.exportable_tls     ← pluggable prover (por/prover.py)
            → 8004 validation registry / coordinator → payout
```

Default: **no** dedicated notary peer; the requesting client is the MPC **verifier**.
Portable/offline notary attestations and threshold k-of-n are **policy opt-ins** only.

| Layer | Module | Role |
|-------|--------|------|
| Trace + AID | `por/execution.py` | VET-style step; Şen PGP obligation shape |
| Prover | `por/prover.py` | **TLSNotary** (default target), `harness` for tests |
| Settlement | `por/payment.py`, `por/settlement.py` | Pay-in → PGP → payout; 8004 stake or sponsor |

Cryptographic profile on the wire: **`dx_dctls_export.v0`** (exportable TLS /
zkTLS family). **TLSNotary** is an implementation choice (`prover: tlsnotary`),
not a separate protocol extension.

## Why TLSNotary / zkTLS for this product

- Experts call **two HTTPS APIs** from the node process (`api.anthropic.com`,
  `api.openai.com`) — ideal for MPC-TLS / notarized TLS (VET “Web Proofs” for
  secret-bearing black-box tools).
- Proves the **upstream LLM call** happened on that server-side channel.
- Composes with Şen **pay-in → execute → PGP → payout** and EIP-8004
  **validation registry** as the evidence layer.
- TEE-only attestation would require running inference inside our enclave, not
  proving calls to vendor APIs.

## Enabling the prover

```bash
export POR_TLS_PROVER=tlsnotary   # harness (default) | tlsnotary
```

Wire TLSNotary session capture from the expert’s HTTP client into
`build_proof_obligation(..., session_material={...})` when the library/CLI is
connected (`por/prover.py`).

## Request envelope fields

- **`mpc_session`** (`por.mpc_session.v0`, mode `inline_2p_v0`): `verifier_peer_id` of the
  client in the live session; included in `request_binding` so the expert cannot swap verifiers.
- **`proof_requirements`**: reserved; execution proof is carried on the **response**
  (`execution_trace`), not by setting `proof_requirements` on the request.
- **`payment_terms`**: funding path (stake / sponsor); canonical terms are part of
  `request_binding`; see `docs/por_8004_execution_settlement.md`.

## Allowed upstream hosts

| `provider_mode` | Host |
|-----------------|------|
| `anthropic` | `api.anthropic.com` |
| `openai` | `api.openai.com` |

## Related docs

- `docs/por_8004_execution_settlement.md` — payment + 8004
- `docs/por_payment_zktls.md` — pay-in / payout schemes
