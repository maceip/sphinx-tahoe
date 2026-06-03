# oblivious-core

Constant-time oblivious top-K selection in Rust — the in-TEE hardening of
`por/oblivious.py` (task H4-port / #18).

## Build (PyO3 extension)

From repo root (uses project venv if present):

```bash
./scripts/build-oblivious-core.sh
```

When installed, `por.oblivious.oblivious_top_k` uses the Rust CMOV path automatically
(production calls without `on_access`). Access-trace tests still use the Python
reference implementation.

## Status

| Layer | Status |
|-------|--------|
| Rust primitive + tests | Done |
| PyO3 → `por/oblivious.py` | Done (optional local install) |
| Nitro EIF image | Pending — add to `Dockerfile.matcher-real` |

## Why

Inside the TEE the operator can't read content but can watch access patterns and
timing. The Python `ct_select` keeps the *memory-access order* data-independent,
but the interpreter still branches on secret data. This crate uses [`subtle`](https://docs.rs/subtle)'s branchless
conditional selects so the *branch and timing trace* are data-independent too.

Verified against a plain reference (`cargo test`) and against `por/oblivious.py`
when the extension is built (`tests/test_oblivious_rust.py`).
