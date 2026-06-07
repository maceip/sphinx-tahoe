"""Tests for Expert Pick: recommendation + reputation-weighted consensus."""

from __future__ import annotations

import json

import pytest

from tenet.expert_pick import (
    ExpertPick,
    ExpertPickError,
    Option,
    consensus,
    parse_pick,
    recommend,
)

OPTS = [Option("a", "Option A"), Option("b", "Option B"), Option("c", "Option C")]


def _llm(pick="a", ranking=("a", "b", "c"), conf=0.9, disclosures=("none",), wrap=False):
    payload = json.dumps({"pick": pick, "ranking": list(ranking), "reasoning": "best on merit",
                          "confidence": conf, "disclosures": list(disclosures)})
    text = f"Here is my pick:\n```json\n{payload}\n```" if wrap else payload
    return lambda _prompt: text


# --------------------------------------------------------------------------- #
# single expert
# --------------------------------------------------------------------------- #


def test_recommend_parses_pick():
    pick = recommend("which?", OPTS, llm=_llm(pick="b"), expert_id="e1")
    assert pick.pick_id == "b"
    assert pick.expert_id == "e1"
    assert pick.ranking[0] == "b"  # winner floated to front
    assert "none" in pick.disclosures


def test_parse_handles_prose_wrapped_json():
    pick = recommend("which?", OPTS, llm=_llm(pick="c", wrap=True))
    assert pick.pick_id == "c"


def test_ranking_completed_when_options_omitted():
    pick = parse_pick(json.dumps({"pick": "a", "ranking": ["a"], "confidence": 0.5}), OPTS)
    assert set(pick.ranking) == {"a", "b", "c"}  # b, c appended


def test_unknown_pick_rejected():
    with pytest.raises(ExpertPickError, match="unknown option"):
        recommend("which?", OPTS, llm=lambda _p: '{"pick":"z"}')


def test_no_json_rejected():
    with pytest.raises(ExpertPickError, match="did not contain JSON"):
        recommend("which?", OPTS, llm=lambda _p: "I think option A is great.")


def test_confidence_clamped():
    pick = recommend("which?", OPTS, llm=_llm(conf=9.9))
    assert pick.confidence == 1.0


def test_need_two_options():
    with pytest.raises(ExpertPickError, match="at least two"):
        recommend("which?", [Option("a", "A")], llm=_llm())


# --------------------------------------------------------------------------- #
# consensus (the anti-gaming core)
# --------------------------------------------------------------------------- #


def _pick(expert_id, pick_id, ranking):
    return ExpertPick(pick_id=pick_id, ranking=tuple(ranking), reasoning="", confidence=0.8, expert_id=expert_id)


def test_consensus_majority_wins():
    picks = [
        _pick("e1", "a", ["a", "b", "c"]),
        _pick("e2", "a", ["a", "c", "b"]),
        _pick("e3", "b", ["b", "a", "c"]),
    ]
    c = consensus(picks, OPTS)
    assert c.pick_id == "a"
    assert c.agreement == pytest.approx(2 / 3)
    assert c.ranking[0] == "a"


def test_consensus_reputation_weighting_can_override_count():
    # 2 low-rep experts say "b", 1 high-rep expert says "a" -> weight decides
    picks = [_pick("low1", "b", ["b", "a", "c"]), _pick("low2", "b", ["b", "a", "c"]), _pick("hi", "a", ["a", "b", "c"])]
    weights = {"low1": 0.2, "low2": 0.2, "hi": 1.0}
    c = consensus(picks, OPTS, weight_fn=lambda e: weights[e])
    assert c.pick_id == "a"  # 1.0 weight beats 0.4 combined


def test_consensus_excludes_flagged_experts():
    picks = [_pick("good", "a", ["a", "b", "c"]), _pick("flagged", "b", ["b", "a", "c"])]
    # flagged expert has weight 0 -> dropped
    c = consensus(picks, OPTS, weight_fn=lambda e: 0.0 if e == "flagged" else 1.0)
    assert c.pick_id == "a"
    assert "flagged" in c.excluded_experts
    assert "good" in c.contributing_experts


def test_consensus_all_flagged_fails_closed():
    picks = [_pick("x", "a", ["a", "b", "c"])]
    with pytest.raises(ExpertPickError, match="excluded"):
        consensus(picks, OPTS, weight_fn=lambda _e: 0.0)


def test_consensus_borda_breaks_ties_on_overall_ranking():
    # split first-choice, but b is consistently 2nd -> b should rank high overall
    picks = [_pick("e1", "a", ["a", "b", "c"]), _pick("e2", "c", ["c", "b", "a"])]
    c = consensus(picks, OPTS)
    # a and c tie on plurality (deterministic winner = "a"); b is everyone's #2
    assert "b" in c.ranking
    assert c.ranking.index("b") <= 1
