# Conditional payments on the base envelope (zkTLS / Şen-style)

Payments ride on **`payment_terms`** in `por.app.v1`. No TLSNotary extension negotiation is required. Relays and supernodes treat the forward payload as opaque JSON.

## Paper mapping (Şen et al., ePrint 2026/277)

| Paper phase | Tenet field / behavior |
|-------------|-------------------------|
| **Pay-in** (premium locked before work) | `payment_terms.pay_in` — expert refuses upstream until verified (`POR_PAYMENT_VERIFY`) |
| **Execute** | Normal expert path: upstream LLM/API call |
| **PGP** (proof generation) | Off-envelope exportable TLS proof (`dx-DCTLS` / zkTLS); `proof_obligation` on `payment_settlement` |
| **Payout** | `payment_terms.payout` — released by coordinator / contract when proof matches `release` |

The paper’s point for decentralized settings: **one O(1) prover session** plus **threshold verifiers** (DVRF + TSS) so payout is not gated on a single designated notary. Tenet keeps that logic **off the mixnet**; the envelope only carries commitments and status.

## vs x402 (HTTP 402)

x402 is **pay → retry HTTP** on the same URL. Tenet is **pay → route through mixnet → expert executes → prove → payout**. The receipt on the return stream is `payment_settlement`, not `PAYMENT-RESPONSE` headers.

## `payment_terms` shape (`por.payment_terms.v0`)

```json
{
  "type": "por.payment_terms.v0",
  "scheme": "zktls_conditional_v0",
  "request_binding": "0x…",
  "pay_in": {
    "ref": "escrow-or-channel-id",
    "amount": "1000",
    "asset": "USDC",
    "verified": true
  },
  "payout": {
    "payee": "expert_peer_id_or_address",
    "amount": "1000",
    "asset": "USDC"
  },
  "release": {
    "predicate": "tls_upstream_response",
    "allowed_hosts": ["api.anthropic.com"]
  },
  "not_after": 1717200000
}
```

`request_binding` MUST equal `request_binding_hash(envelope)` so pay-in locks this job, not another prompt.

## Expert behavior

1. Parse `payment_terms`; if absent, behave as today.
2. If present, verify pay-in (`POR_PAYMENT_VERIFY`: `harness` | `trust` | `strict`).
3. Call upstream only after pay-in passes.
4. On final stream frame, attach `payment_settlement` with `status: proof_due` and empty `proof_obligation` until zkTLS is wired.

## Client helper

```python
from por.envelope import PromptRequestEnvelope
from por.payment import build_payment_terms

env = PromptRequestEnvelope.visible_prompt("…", selected_peer_id="expert_1")
env = PromptRequestEnvelope.visible_prompt(
    …,
    request_id=env.request_id,
    payment_terms=build_payment_terms(
        env,
        pay_in={"ref": "…", "amount": "1000", "asset": "USDC", "verified": True},
        payout={"payee": "expert_1", "amount": "1000", "asset": "USDC"},
        release={"predicate": "tls_upstream_response", "allowed_hosts": ["api.openai.com"]},
    ),
)
```

## Not in scope yet

- On-chain escrow / x402 facilitator integration
- Live TLSNotary prover in the expert process
- Threshold verifier network (DVRF/TSS) — belongs with settlement coordinator
