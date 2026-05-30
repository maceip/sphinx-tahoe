# P-OR Replay And Restart Policy

Status: MVP runtime policy.

## Decision

P-OR circuit state is RAM-only in the MVP.

Relays and expert exits keep per-circuit symmetric keys, outbound link IDs, and
the highest accepted nonce in process memory. That state is not silently
persisted across restart.

## Failure Semantics

When a relay or expert process restarts, all active return circuits through that
node are gone. Later circuit packets for those link IDs are rejected as
`circuit_missing`; the client must retry the request or build a new circuit.

When a packet arrives with a nonce less than or equal to the circuit high
watermark, the node drops it and emits `circuit_replay`. It does not forward a
replacement packet and does not try to repair the stream.

Malformed circuit packets are dropped and logged as `circuit_malformed`.
Expired or invalid forward packets are dropped and logged as
`forward_expired_or_invalid`.

## Why RAM-Only First

RAM-only state has simple privacy and operator properties:

- no circuit keys written to disk
- no replay window ambiguity after process restart
- no recovery format that can drift from the wire format
- obvious product behavior when a relay dies: the stream fails and the client
  retries

## Bounded Persistence Later

Bounded circuit-table persistence can be added later if restart recovery becomes
worth the extra risk. That design must define:

- encrypted-at-rest circuit key storage
- TTL and maximum persisted circuit count
- crash-consistent high-watermark updates
- explicit operator opt-in
- tests proving replayed packets are still rejected after restart

Until that exists, there is no silent replay recovery.
