"""Expert Pick: a trustworthy "which option should I choose?" recommendation.

You can't trust Google/SEO/affiliate-ranked results. Here you pay (EURD over
x402) for an *expert's* pick among your options — and the anti-gaming answer is
**reputation-weighted multi-expert consensus**: a single expert can be bribed to
recommend, but a quorum of independent, reputation-staked experts can't be (you'd
have to corrupt a weighted majority, and flagged experts are down-weighted to
zero). Every pick carries the expert's disclosures for transparency.

The LLM is injected (``llm: Callable[[str], str]``) so this is testable and
provider-agnostic; ``anthropic_llm`` is a real adapter (API key injected).
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Sequence

LLM = Callable[[str], str]


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    detail: str = ""


@dataclass(frozen=True)
class ExpertPick:
    pick_id: str
    ranking: tuple[str, ...]
    reasoning: str
    confidence: float
    disclosures: tuple[str, ...] = field(default_factory=tuple)
    expert_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "pick_id": self.pick_id, "ranking": list(self.ranking),
            "reasoning": self.reasoning, "confidence": self.confidence,
            "disclosures": list(self.disclosures), "expert_id": self.expert_id,
        }


class ExpertPickError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# prompt + parse
# --------------------------------------------------------------------------- #


def build_pick_prompt(question: str, options: Sequence[Option], *, context: str | None = None, persona: str | None = None) -> str:
    persona = persona or "an impartial domain expert with no affiliations"
    lines = [
        f"You are {persona}. A user must choose among the options below.",
        "Pick the best option on genuine merit/quality — NOT popularity, ads, or SEO.",
        "Disclose any conflict of interest or affiliation; if none, say so.",
        "",
        f"QUESTION: {question}",
    ]
    if context:
        lines.append(f"CONTEXT: {context}")
    lines.append("OPTIONS:")
    for o in options:
        lines.append(f"  - id={o.id} | {o.label}" + (f" | {o.detail}" if o.detail else ""))
    lines += [
        "",
        "Respond with ONLY a JSON object, no prose:",
        '{"pick": "<id>", "ranking": ["<id>", ...best to worst...], '
        '"reasoning": "<why>", "confidence": <0..1>, "disclosures": ["<conflict or \'none\'>"]}',
    ]
    return "\n".join(lines)


def parse_pick(raw: str, options: Sequence[Option], *, expert_id: str = "") -> ExpertPick:
    valid_ids = {o.id for o in options}
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ExpertPickError("expert response did not contain JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ExpertPickError(f"unparseable expert JSON: {exc}") from exc

    pick = str(data.get("pick", ""))
    if pick not in valid_ids:
        raise ExpertPickError(f"expert picked an unknown option: {pick!r}")
    ranking = tuple(str(x) for x in data.get("ranking", []) if str(x) in valid_ids)
    # the explicit pick is the winner: always float it to the front (resolves any
    # model inconsistency between `pick` and `ranking`)
    ranking = (pick,) + tuple(r for r in ranking if r != pick)
    # append any options the model omitted so the ranking is complete
    ranking = ranking + tuple(o.id for o in options if o.id not in ranking)
    conf = float(data.get("confidence", 0.5))
    conf = min(1.0, max(0.0, conf))
    disclosures = tuple(str(d) for d in data.get("disclosures", []) or ())
    return ExpertPick(
        pick_id=pick, ranking=ranking, reasoning=str(data.get("reasoning", "")),
        confidence=conf, disclosures=disclosures, expert_id=expert_id,
    )


def recommend(
    question: str,
    options: Sequence[Option],
    *,
    llm: LLM,
    context: str | None = None,
    expert_id: str = "",
    persona: str | None = None,
) -> ExpertPick:
    if len(options) < 2:
        raise ExpertPickError("need at least two options to pick from")
    prompt = build_pick_prompt(question, options, context=context, persona=persona)
    return parse_pick(llm(prompt), options, expert_id=expert_id)


# --------------------------------------------------------------------------- #
# anti-gaming: reputation-weighted multi-expert consensus
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConsensusPick:
    pick_id: str
    ranking: tuple[str, ...]
    agreement: float                 # fraction of weight on the winning pick
    contributing_experts: tuple[str, ...]
    excluded_experts: tuple[str, ...]  # flagged/zero-weight experts dropped
    picks: tuple[ExpertPick, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "pick_id": self.pick_id, "ranking": list(self.ranking),
            "agreement": self.agreement,
            "contributing_experts": list(self.contributing_experts),
            "excluded_experts": list(self.excluded_experts),
            "picks": [p.to_dict() for p in self.picks],
        }


def consensus(
    picks: Sequence[ExpertPick],
    options: Sequence[Option],
    *,
    weight_fn: Callable[[str], float] | None = None,
) -> ConsensusPick:
    """Aggregate independent expert picks into a reputation-weighted decision.

    ``weight_fn(expert_id) -> float`` returns each expert's weight (e.g. from the
    reputation ledger; flagged experts return 0 and are excluded). The winning
    pick is the weighted plurality; the overall ranking is a weighted Borda count.
    """
    if not picks:
        raise ExpertPickError("no expert picks to aggregate")
    weight_fn = weight_fn or (lambda _e: 1.0)

    pick_weight: dict[str, float] = defaultdict(float)
    borda: dict[str, float] = defaultdict(float)
    contributing: list[str] = []
    excluded: list[str] = []
    total_weight = 0.0
    n = len(options)

    for p in picks:
        w = max(0.0, weight_fn(p.expert_id))
        if w <= 0.0:
            excluded.append(p.expert_id)
            continue
        contributing.append(p.expert_id)
        total_weight += w
        pick_weight[p.pick_id] += w
        for rank_index, oid in enumerate(p.ranking):
            borda[oid] += w * (n - rank_index)

    if total_weight <= 0.0:
        raise ExpertPickError("all contributing experts were excluded (flagged)")

    winner = max(pick_weight.items(), key=lambda kv: (kv[1], kv[0]))[0]
    agreement = pick_weight[winner] / total_weight
    ranking = tuple(sorted((o.id for o in options), key=lambda oid: (-borda[oid], oid)))
    return ConsensusPick(
        pick_id=winner, ranking=ranking, agreement=agreement,
        contributing_experts=tuple(contributing), excluded_experts=tuple(excluded),
        picks=tuple(picks),
    )


# --------------------------------------------------------------------------- #
# real LLM adapter (Anthropic Messages API; key injected)
# --------------------------------------------------------------------------- #


def anthropic_llm(api_key: str, *, model: str = "claude-sonnet-4-6", max_tokens: int = 1024, timeout: float = 60.0) -> LLM:
    """Return an LLM callable backed by the Anthropic Messages API."""

    def _call(prompt: str) -> str:
        body = json.dumps({
            "model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body, method="POST",
            headers={
                "x-api-key": api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        parts = data.get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text")

    return _call
