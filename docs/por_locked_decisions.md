# Locked decisions: execution proof + payment (P-OR)

Status: **locked** for implementation and review (2026-05-31). Changes require an
explicit revision to this file.

## Architecture

| Topic | Decision |
|-------|----------|
| **2P MPC** | Default path uses **existing online coordination** (client ↔ expert on a job). Expert = **prover**; requesting client = **verifier**. No expert-driven verifier discovery. |
| **Notary role** | **No** dedicated notary peer class or network-operated notary fleet. TLSNotary “notary” semantics are **optional later** only when a party that was **not** in the live 2P window must verify (sponsor / 8004 registry / threshold). |
| **Portable attestations** | **Deferred** for default jobs. Wire still uses `dx_dctls_export.v0` / `exportable_tls` so blobs can be stored; v1 does not require offline notary signatures. |
| **Threshold k-of-n** | **Deferred** unless settlement/reputation policy requires verifiers who were not in the live session (Şen-style). Not a mixnet peer type — ordinary clients when enabled. |
| **Relays / supernodes** | **Opaque** to `payment_terms`, `execution_trace`, and MPC setup. |
| **TLSNotary placement** | **Prover back end** (`por/prover.py`, `POR_TLS_PROVER=tlsnotary`), **not** `client_extensions` / `tlsnotary_execution_v1`. |
| **Upstream hosts** | **Only** `api.anthropic.com` and `api.openai.com` from the expert process. |
| **Payment wire** | **`payment_terms`** on base `por.app.v1` envelope; schemes in `docs/por_payment_zktls.md`. |
| **Reputation / expert promotion** | **Other team.** Execution proof is **necessary for job payout**, **not sufficient** for expert status. 8004 validation registry + feedback consume `execution_trace` evidence (`tenet.dx_dctls_execution.v0`). |
| **Browser TLSNotary** | **Out of scope** — server-side expert HTTP only. |

## Wire fields

| Field | Role |
|-------|------|
| `payment_terms` | Pay-in → execute → PGP → payout; `request_binding` locks job + terms + verifier. |
| `mpc_session` | Binds **verifier** identity before upstream (`por.mpc_session.v0`). |
| `execution_trace` | VET-shaped response on final `done` frame. |
| `proof_obligation` | Şen PGP slot; `exportable_tls` from prover. |
| `proof_requirements` | **Reserved** on request; proof rides on response. |

## Threat model (acknowledged)

| Risk | Mitigation in this layer |
|------|---------------------------|
| Expert alone forges TLS | MPC verifier in 2P session. |
| Expert + verifier collude | Reputation/registry must not treat one proof as expert promotion; stake slash + multi-party validation when policy requires. |
| Wrong payout / swapped terms | `request_binding` includes canonical `payment_terms` (excluding self-hash). |
| Expert swaps verifier mid-job | `mpc_session` in binding; expert rejects mismatch. |
| Harness / trust modes in production | **Forbidden** for real settlement; see review flags below. |

## Implementation map

| Concern | Module / doc |
|---------|----------------|
| Envelope + binding | `por/envelope.py`, `por/payment.py` |
| Trace + obligation | `por/execution.py` |
| Prover | `por/prover.py` |
| Expert gate + completion | `por/provider.py`, `por/settlement.py` |
| Narrative | `docs/por_execution_proof.md`, `docs/por_8004_execution_settlement.md` |

## Review flags (must not ship to production settlement)

1. **`POR_TLS_PROVER=harness`** — stub proof only; never release payout on harness export alone.
2. **`POR_PAYMENT_VERIFY=harness|trust`** — does not prove on-chain / sponsor approval; `strict` required for real pay-in.
3. **`POR_PROVIDER=harness`** — no real upstream LLM call; `llm_called` false in settlement.
4. **MPC session not started** — `proof_obligation.status` may be `awaiting_session_capture`; payout must stay pending.
5. **Settlement coordinator** — must check `release` predicate against verified `exportable_tls`, not `payment_settlement` status alone.
6. **Transport harness** — UDP/QUIC demos are not production daemon wire; see `docs/por_wire_protocol.md` §19.

## Not in scope (this track)

- On-chain escrow, sponsor API, stake registry reader, automatic `payout_released`.
- TLSNotary library wiring into expert HTTP client (integration point documented).
- Prompt hiding (`confidential_prompt_v1`).
- Expert routing / memory-fit / Sybil policy.
