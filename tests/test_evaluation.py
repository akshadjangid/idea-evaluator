import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from evaluation import DEFAULT_WEIGHTS, rules_review, score_idea, sim


def idea(**updates):
    value = {
        "id": "idea-1", "title": "Campus energy usage monitor",
        "desc": "A web dashboard helps campus staff track building electricity usage and reduce waste.",
        "budget": 1500, "weeks": 10, "complexity": 2, "skill": 2,
        "impact": 4, "arch": "cloud", "stack": "Python, AWS Lambda, DynamoDB",
        "sdg": "9", "why": "Supports resilient infrastructure through energy visibility.",
    }
    value.update(updates)
    return value


def test_default_weights_total_100():
    assert sum(DEFAULT_WEIGHTS.values()) == 100


def test_score_is_bounded_and_has_six_criteria():
    result = score_idea(idea(), [], DEFAULT_WEIGHTS)
    assert set(result["scores"]) == set(DEFAULT_WEIGHTS)
    assert 0 <= result["total"] <= 100
    assert all(0 <= value <= 10 for value in result["scores"].values())


def test_weights_must_add_to_100():
    bad = dict(DEFAULT_WEIGHTS, innovation=19)
    try:
        score_idea(idea(), [], bad)
        assert False, "Expected invalid weights to fail"
    except ValueError as exc:
        assert "add up to 100" in str(exc)


def test_similarity_is_jaccard_and_bounded():
    assert sim("cloud campus energy", "cloud campus energy") == 1.0
    assert 0 <= sim("campus energy", "student attendance") <= 1
    assert sim("!!!", "???") == 0.0


def test_similarity_changes_innovation_estimate():
    candidate = idea()
    duplicate = {**idea(), "id": "idea-2"}
    first = score_idea(candidate, [], DEFAULT_WEIGHTS)
    compared = score_idea(candidate, [duplicate], DEFAULT_WEIGHTS)
    assert compared["similarity"] == 1.0
    assert compared["scores"]["innovation"] < first["scores"]["innovation"]


def test_rules_review_returns_structured_advice_and_disclaimer():
    result = rules_review(idea(arch="local", budget=9000, weeks=20), [])
    assert isinstance(result["risks"], list) and result["risks"]
    assert isinstance(result["suggestions"], list) and result["suggestions"]
    assert isinstance(result["tech"], list) and result["tech"]
    assert "not proof of copying" in result["disclaimer"]
    assert result["method"] == "deterministic-rules-v1"


def test_rules_review_identifies_closest_idea():
    existing = {**idea(), "id": "old", "title": "Campus energy usage monitor"}
    result = rules_review(idea(), [existing])
    assert result["closest"] == existing["title"]
    assert result["similarity"] > 0
