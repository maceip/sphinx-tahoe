# Hybrid Return Path — Traffic Analysis Requirements

Yodel is cited in `HYBRID_RETURN_PATH_SPEC.txt` for **constant-rate mixing**. This
project uses only part of that model today: fixed-size circuit cells, symmetric
peel path, and optional self-heal. **Constant-rate cover on the return path is
not automatic from “Yodel-type circuits.”**

See spec §2 non-goals for the prototype boundary.

## Requirements

| ID | Status | Requirement |
|----|--------|-------------|
| **TA-1** | Deferred | Path-wide constant-rate circuit cover (every hop, indistinguishable dummies). Out of MVP. Full Yodel-style TA mitigation. |
| **TA-2** | MVP | Session-scoped exit pacing + keepalives: `PacedCircuitStream`, `CIRCUIT_PACE_INTERVAL_MS`, active between first `offer()` and `close()`. |
| **TA-3** | MVP | **Claims:** Do not describe streaming return as mixnet-grade or GPA-resistant. Use “encrypted relay chain” / “circuit return path.” |

## TA-3 implementation (20%)

Honest claims are **encoded in code**, not only docs:

| Location | What |
|----------|------|
| `sphinxmix/ta_claims.py` | `ta_claim`, `ta_not`, forbidden copy checker |
| `por/envelope.py` | Rejects streaming `return_descriptor` without `ta_claim` |
| `por/expert_mode.py` | Default descriptor via `streaming_return_descriptor()` |
| `sphinxmix/mixnet.py` | `pending_circuits[*].return_claim` |
| `sim_mixnet_anthropic_proxy.py` | `X-Return-Path-Claim`, `X-Return-Path-Not` headers in the in-process proxy harness |
| `test_ta_claims.py` | Regression tests |
| `scripts/check_ta_claims.py` | Doc oversell scanner (CI hook) |
| `por/udp_demo.py` | Envelope uses `streaming_return_descriptor()` |

The proxy headers above are emitted by an in-process proxy harness. They are
claim metadata for review and regression tests, not proof that a production
provider gateway or production relay wire exists.

Example descriptor fields:

```json
{
  "mode": "hybrid_return_path_v2",
  "stream": true,
  "ta_claim": "encrypted_relay_chain",
  "ta_claim_detail": "circuit_return_path",
  "ta_not": ["not_gpa_resistant", "not_mixnet_streaming", "not_path_wide_cover"]
}
```

Use `assert_honest_streaming_copy(text)` in docs/marketing CI if needed later.

Run `python3 scripts/check_ta_claims.py` before merge (scans tracked docs for
forbidden oversell phrases).

## Not the same thing

| Mechanism | Purpose |
|-----------|---------|
| Keepalive (spec §9.3) | Keep circuit state alive across idle gaps (TTL). |
| TA-2 pacing | Flatten token bursts; steady packet cadence during an active stream. |
| TA-1 constant-rate cover | Traffic-analysis resistance at all hops. **Not implemented.** |

Forward `FLAG_DUMMY` cover applies to **forward Outfox** packets, not circuit
return streaming.

## Code anchors (so origins are findable)

- `sphinxmix/OutfoxParams.py` — `CIRCUIT_PACE_INTERVAL_MS`
- `sphinxmix/OutfoxNode.py` — `PacedCircuitStream` (`offer`, `close`, `drain_all`)
- `sphinxmix/mixnet.py` — `create_paced_circuit_stream()`, `stream_paced_drain()`
- `sim_mixnet_anthropic_proxy.py` — paced circuit return default (`CIRCUIT_PACE_ENABLED=1`)
- `sphinxmix/ta_claims.py` — TA-3 claim constants + validators
- `test_ta_claims.py` — TA-3 regression
- `test_mixnet.py` — `test_paced_stream_*`

## Future (after TA-2)

- Poisson jitter / batching (Loopix-style, session-only)
- First-hop relay cover during active session
- TA-1 only if product accepts latency + bandwidth cost
