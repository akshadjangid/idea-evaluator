"""Deterministic, dependency-free project idea evaluation engine."""
from __future__ import annotations
import re
from typing import Any

DEFAULT_WEIGHTS = {"innovation": 20, "feasibility": 20, "cost": 15, "time": 15, "impact": 20, "scalability": 10}
LABELS = {"innovation": "Innovation", "feasibility": "Feasibility", "cost": "Cost", "time": "Implementation time", "impact": "Social impact", "scalability": "Scalability"}
TIPS = {
    "innovation": "Clarify what is different from existing solutions and add a distinctive feature or underserved user group.",
    "feasibility": "Reduce scope, validate the hardest technical assumption early, and use tools your team already knows.",
    "cost": "Estimate hosting, storage, email, and third-party API costs; prefer open-source tools and free-tier services.",
    "time": "Split work into two-week milestones and deliver a small end-to-end prototype first.",
    "impact": "Identify a specific beneficiary group and define a measurable outcome linked to the selected SDG.",
    "scalability": "Separate UI, API, and persistence; use managed services and design for pagination and bounded requests.",
}
TECH_HINTS = [
    (r"\b(web|website|portal|dashboard|browser)\b", ["HTML/CSS/JavaScript", "REST API", "responsive design"]),
    (r"\b(cloud|serverless|aws|lambda)\b", ["AWS Lambda", "Amazon API Gateway", "Amazon DynamoDB"]),
    (r"\b(machine learning|prediction|classif|recommend|nlp|text)\b", ["scikit-learn", "TF-IDF / cosine similarity", "FastAPI"]),
    (r"\b(mobile|android|ios|app)\b", ["Progressive Web App", "Flutter (optional)"]),
    (r"\b(database|records|inventory|library|attendance)\b", ["SQLite for local prototype", "DynamoDB or PostgreSQL for cloud persistence"]),
]

def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", str(text or "").lower()))

def sim(a: str, b: str) -> float:
    x, y = words(a), words(b)
    return len(x & y) / len(x | y) if x and y else 0.0

def clamp(value: float) -> float:
    return max(0.0, min(10.0, float(value)))

def score_idea(idea: dict[str, Any], others: list[dict[str, Any]], weights: dict[str, int] | None = None) -> dict[str, Any]:
    weights = dict(weights or DEFAULT_WEIGHTS)
    if set(weights) != set(DEFAULT_WEIGHTS) or any(not isinstance(v, int) or v < 0 for v in weights.values()) or sum(weights.values()) != 100:
        raise ValueError("Scoring weights must be non-negative integers that add up to 100")
    text = f"{idea.get('title', '')} {idea.get('desc', '')}"
    comparisons = [(sim(text, f"{o.get('title', '')} {o.get('desc', '')}"), o) for o in others if o.get("id") != idea.get("id")]
    closest_score, closest = max(comparisons, key=lambda x: x[0], default=(0.0, None))
    budget = max(0.0, float(idea.get("budget", 0) or 0))
    weeks = max(1.0, float(idea.get("weeks", 1) or 1))
    complexity = max(1.0, min(3.0, float(idea.get("complexity", 2) or 2)))
    skill = max(1.0, min(3.0, float(idea.get("skill", 2) or 2)))
    impact = max(1.0, min(5.0, float(idea.get("impact", 1) or 1)))
    arch = idea.get("arch") or "local"
    scores = {
        "innovation": clamp(10 - closest_score * 14),
        "feasibility": clamp(10 - (complexity - 1) * 2.5 + (skill - 2) * 1.5),
        "cost": 10 if budget <= 500 else 8 if budget <= 2000 else 6 if budget <= 5000 else 4 if budget <= 10000 else 2,
        "time": 10 if weeks <= 10 else 8 if weeks <= 14 else 5 if weeks <= 18 else 2,
        "impact": clamp(impact * 2 + (1.5 if idea.get("sdg") and len(str(idea.get("why", "")).strip()) >= 20 else 0)),
        "scalability": {"cloud": 10, "hybrid": 6, "local": 2}.get(arch, 2),
    }
    total = round(sum(scores[k] * weights[k] / 10 for k in weights))
    return {"scores": {k: round(v, 2) for k, v in scores.items()}, "total": total,
            "weights": weights, "similarity": round(closest_score, 4),
            "closest": closest.get("title", "") if closest else ""}

def rules_review(idea: dict[str, Any], others: list[dict[str, Any]], weights: dict[str, int] | None = None) -> dict[str, Any]:
    result = score_idea(idea, others, weights)
    scores = result["scores"]
    weak = [k for k, v in scores.items() if v < 6]
    tech = []
    source = f"{idea.get('title', '')} {idea.get('desc', '')} {idea.get('stack', '')}".lower()
    for pattern, suggestions in TECH_HINTS:
        if re.search(pattern, source):
            tech.extend(suggestions)
    tech = list(dict.fromkeys(tech))[:5] or ["HTML/CSS/JavaScript", "Python", "SQLite for local testing"]
    risks = []
    if result["similarity"] >= 0.35:
        risks.append("Meaningful keyword overlap with an existing submission; compare scope and intended users manually.")
    if float(idea.get("budget", 0) or 0) > 5000:
        risks.append("The stated budget exceeds ₹5,000; verify recurring hosting and third-party service costs.")
    if float(idea.get("weeks", 1) or 1) > 16:
        risks.append("The estimated timeline is long for a semester project; reduce scope or split delivery into milestones.")
    if idea.get("arch", "local") == "local":
        risks.append("The current technology description does not clearly identify a cloud deployment path.")
    if not risks:
        risks.append("Validate assumptions with target users and test a small end-to-end prototype before full implementation.")
    suggestions = [TIPS[k] for k in weak[:4]]
    if not suggestions:
        suggestions = ["Define measurable acceptance criteria and test with representative users.", "Document data privacy, failure handling, and deployment costs."]
    if result["closest"]:
        closest_why = f"Estimated word overlap is {round(result['similarity'] * 100)}%; this is a rough text heuristic, not evidence of copying."
        summary = f"Rules-based estimate: {result['total']}/100. The closest title match is {result['closest']}."
    else:
        closest_why = "No comparison idea was available."
        summary = f"Rules-based estimate: {result['total']}/100. No existing idea was available for comparison."
    return {"innovation": scores["innovation"], "summary": summary, "risks": risks[:4],
            "suggestions": suggestions, "tech": tech, "closest": result["closest"],
            "closestWhy": closest_why, "similarity": result["similarity"],
            "method": "deterministic-rules-v1",
            "disclaimer": "A heuristic screening aid only; similarity is not proof of copying and this is not human-level understanding."}
