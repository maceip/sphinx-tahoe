# P-OR execution attestation (v0)

Minimal proof-of-execution for expert exits, aligned with [EIP-8004](https://eips.ethereum.org/EIPS/eip-8004) **Validation Registry** (`validationRequest` / `validationResponse`).

## What this is

- **Runtime execution** evidence: the exit peer actually called (or simulated) an upstream LLM/API for this `request_id`.
- Off-chain JSON at `requestURI` / `responseURI`; on-chain commitments via `requestHash` / `responseHash`.
- Returned on the **last streaming frame** as `attestation` when `proof_requirements` is not `none`.

## What this is not

- Not **Identity** or **Reputation** (ERC-8004 registries #1/#2). Assay-style stake scores stay separate.
- Not **input provenance** (WYRIWE / manifest-only claims). Use a different `claim` and tag when you add that layer.
- Not **PreparedTransaction** (ERC-8265 wallet handoff). Composes with 8004 agents but does not replace human tx approval.

## Wire

Request envelope:

```json
"proof_requirements": ["tls_execution"]
```

Final chunk:

```json
{"seq": 2, "data": "", "done": true, "attestation": { ... }}
```

## ERC-8004 field map

| EIP-8004 | Tenet v0 |
|----------|----------|
| `requestURI` | `por://attestation/request/{request_id}` (placeholder; host real HTTPS/IPFS in production) |
| `requestHash` | `keccak256` of canonical request JSON (`0x` + sha256 hex in harness) |
| `response` | `0–100` (`100` harness synthetic pass, `0` until validator scores real zkTLS) |
| `responseURI` | `por://attestation/response/{request_id}` |
| `responseHash` | commitment to response JSON |
| `tag` | `tenet.tls_execution.v0` |

## Evidence families

| Family | When |
|--------|------|
| `harness` | `POR_PROVIDER=harness` — binds peer, prompt/response hashes, `llm_called=no` |
| `zktls` | Live provider or future exportable TLS proof (Şen-style exportable attestation slot in `exportable_tls`) |

## Magicians thread notes

- Posts **#160** (Assay trust-check) and **#162** (self-correction metrics) are ecosystem neighbors, not duplicated here.
- Validation Registry as **evidence layer** (identity vs authority, execution vs reputation) matches **#171**-style framing on the [ERC-8004 thread](https://ethereum-magicians.org/t/erc-8004-trustless-agents/25098).

## Code

- `por/attestation.py` — builders
- `por/provider.expert_reply_with_attestation` — harness / API paths
- `por/node_runtime` — attaches attestation on `done` frames
