"""Oblivious top-K selection for the matcher (H4 — the algorithm layer).

Inside the TEE, the operator cannot *read* content — but it can watch *access
patterns*. If the matcher's memory accesses depend on which expert matched, the
operator learns the match from the access trace even though the data is sealed.
Obliviousness closes that: every query touches every entry in the same order,
the output length is constant, and every data-dependent choice is a constant-time
select rather than a branch or early exit.

This module implements that selection algorithm and is validated by an
access-trace-invariance test (tests/test_oblivious.py): two different score
vectors produce a byte-identical access trace.

Honest scope: this is the *algorithm* + its access-pattern invariance. Hardware
constant-time execution — branchless CMOV instead of Python's value-select, and
ORAM for the manifest store so the property holds against an OS-level adversary
rather than only at the Python level — is the in-TEE (Rust) hardening, still
ahead. See docs/matcher_threat_model.md.
"""

from __future__ import annotations

from typing import Callable, Sequence


DUMMY_INDEX = -1


def ct_select(cond: bool, a, b):
    """Select ``a`` if ``cond`` else ``b`` without a data-dependent access.

    Both arms are already evaluated by the caller; the choice is made by a mask,
    so which value is kept does not change *which memory was touched*. Python
    cannot guarantee hardware constant-time (the TEE port uses a real CMOV); what
    this preserves is the data-independent access pattern the obliviousness test
    checks.
    """
    return a if (1 if cond else 0) else b


def oblivious_top_k(
    scores: Sequence[float],
    k: int,
    *,
    on_access: Callable[[int], None] | None = None,
) -> list[int]:
    """Return ``k`` entry indices in descending score order, data-obliviously.

    Guarantees that do not depend on the score values:

    - exactly ``k`` full linear scans for selection + ``k`` for marking, each over
      all ``n`` entries in index order (uniform access pattern);
    - exactly ``k`` results; a position with no remaining positive entry is
      ``DUMMY_INDEX``, so the count never leaks how many entries scored well;
    - only entries with ``score > 0`` are ever selected (the matcher's relevance
      threshold), enforced as a select, not a branch.

    Ties break toward the lower index (deterministic). ``on_access(i)`` fires on
    every entry touch so the obliviousness test can record the access trace.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    n = len(scores)
    taken = [False] * n
    out: list[int] = []
    for _ in range(k):
        best_idx = DUMMY_INDEX
        best_score = float("-inf")
        best_is_real = False
        for i in range(n):
            if on_access is not None:
                on_access(i)
            eligible = (not taken[i]) and (scores[i] > 0.0)
            better = scores[i] > best_score
            sel = eligible and better
            best_score = ct_select(sel, scores[i], best_score)
            best_idx = ct_select(sel, i, best_idx)
            best_is_real = ct_select(sel, True, best_is_real)
        for i in range(n):
            if on_access is not None:
                on_access(i)
            taken[i] = ct_select(i == best_idx and best_is_real, True, taken[i])
        out.append(best_idx)
    return out
