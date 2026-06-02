# oblivious-core

Constant-time oblivious top-K selection in Rust — the in-TEE hardening of
`por/oblivious.py` (task H4-port / #18).

## Why

Inside the TEE the operator can't read content but can watch access patterns and
timing. The Python `ct_select` keeps the *memory-access order* data-independent,
but the interpreter still branches on secret data, so it isn't instruction-level
constant-time. This crate uses [`subtle`](https://docs.rs/subtle)'s branchless
conditional selects (the CMOV-level guarantee) so the *branch and timing trace*
are data-independent too.

## Guarantees

For `oblivious_top_k(scores, k)` — none depend on the score values:
- exactly `k` full scans for selection + `k` for marking (uniform access);
- exactly `k` outputs; empty slots are `DUMMY_INDEX` (count never leaks);
- only `score > 0` is eligible; ties break to the lower index;
- every secret-dependent choice is a `subtle` conditional select.

Verified against a plain reference (`cargo test`) and confirmed byte-for-byte
identical to `por/oblivious.py` on shared cases.

## Status

The primitive is done and tested. **Remaining integration:** the live enclave
matcher still calls `por/oblivious.py` (Python). Wiring this crate in — via a
PyO3 extension the Python matcher loads, or by moving the selection step into a
Rust workload — is the next step. Scores must be quantised to `u64` (0 = below
threshold) at the call boundary.
