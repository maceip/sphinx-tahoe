# Execution + settlement plan (8004-aligned)

Target: **two server-side HTTPS tools** — `api.anthropic.com`, `api.openai.com`.
Proof: **TLSNotary** (or compatible prover) behind `por/prover.py`; wire front end
is `execution_trace`. See `docs/por_execution_proof.md`.

## Execution (VET + Şen)

| Layer | Choice |
|-------|--------|
| Composition | [VET](https://arxiv.org/abs/2512.15892) — `execution_trace` on final `done` frame |
| Per-tool proof | [Şen et al. 2026/277](https://eprint.iacr.org/2026/277) — `dx_dctls_export.v0` + threshold validators |
| Prover | **TLSNotary** via `por/prover.py` (`POR_TLS_PROVER=tlsnotary`) |
| Code | `por/execution.py`, `por/prover.py`, `por/settlement.py` |

Flow: expert executes → `execution_trace` (AID fragment + step + PGP slot) → coordinator / validators release payout when exportable proof matches `release`.

## Payment (dual path, 8004-friendly)

Default builder: `build_default_tenet_payment_terms(envelope)` — stake if `agent_id` in intent, else sponsored.

| Scheme | When | Pay-in | Who pays gas + expert fee |
|--------|------|--------|---------------------------|
| `erc8004_stake_v0` | Expert has 8004 identity + stake | `pay_in.stake` | Collateral; slash on bad proof (off-chain coordinator first) |
| `sponsored_service_v0` | No stake / bootstrap | `pay_in.sponsor` | **Tenet network** — ERC-4337 gas paymaster + custom service paymaster |
| `erc8183_job_v0` | Optional later | `job_id` funded | Client `fund()` once; evaluator reads validation registry |
| `zktls_conditional_v0` | Legacy strict escrow | `pay_in.verified` | User escrow (avoid for onboarding) |

### Double paymaster (your preference)

1. **Gas** — standard [ERC-4337](https://eips.ethereum.org/EIPS/eip-4337) paymaster + [EIP-7677](https://eips.ethereum.org/EIPS/eip-7677) service (`gas_paymaster: erc4337` in terms).
2. **Expert fee** — `service_paymaster: tenet_sponsor_v0` (custom verifying paymaster or off-chain sponsor ledger that marks `pay_in.verified`).

Both appear under `pay_in.sponsor.covers: ["gas", "expert_fee"]`.

### ERC-8004 hooks

On `payment_settlement.erc8004`:

- **Stake path** — link `agent_registry`, `agent_id`; on success post `validationResponse` + reputation feedback.
- **Sponsor path** — same validation registry tag `tenet.dx_dctls_execution.v0`, evidence `runtime_execution`.

Aligns with Magicians “validation registry as evidence layer” without overloading identity/reputation.

## Wire (base envelope)

```json
{
  "payment_terms": { "scheme": "sponsored_service_v0", ... },
  "done": true,
  "execution_trace": { "type": "por.execution_trace.v0", ... },
  "payment_settlement": { "type": "por.payment_settlement.v0", ... }
}
```

## Env

| Variable | Role |
|----------|------|
| `POR_PAYMENT_VERIFY` | `harness` \| `trust` \| `strict` |
| `TENET_SPONSOR_ID` | Default sponsor for `build_default_tenet_payment_terms` |
| `TENET_SPONSOR_ADDRESS` | Optional on-chain sponsor |

## Build order (recommended)

1. **Now (code)** — trace + terms builders + harness `done` payloads ✓  
2. **Sponsor service** — off-chain API: approve `request_binding` → set `verified` (unblocks experts without stake)  
3. **Stake reader** — read Assay / 8004 stake registry → `stake_sufficient`  
4. **PGP** — wire TLSNotary session capture into `por/prover.py` for anthropic/openai  
5. **On-chain** — validation registry `validationRequest` / `validationResponse` + optional 8183 evaluator hook

## Client example

```python
from por.envelope import PromptRequestEnvelope
from por.payment import build_default_tenet_payment_terms

base = PromptRequestEnvelope.visible_prompt("…", selected_peer_id="expert_1")
env = PromptRequestEnvelope.visible_prompt(
    "…",
    selected_peer_id="expert_1",
    request_id=base.request_id,
    payment_terms=build_default_tenet_payment_terms(base),
    extra_intent={"agent_registry": "eip155:8453:0x…", "agent_id": "42"},
)
```
