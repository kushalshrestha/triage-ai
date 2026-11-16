"""Real measured effect of enabling the opt-in injection classifier
(ADR-0031) against the full categorized safety golden set, including
`realistic_benign` — the category that doesn't exist in the
pattern-only eval's framing because it's not adversarial at all, and
is exactly where the real cost shows up.

Not marked @pytest.mark.costly — no Claude API cost, just a local
HuggingFace model (same resource class as the cross-encoder reranker
already used freely in tests/evals/test_retrieval_eval.py).
"""
import json
from pathlib import Path

from app.guardrails.injection import is_likely_injection
from app.models import EvalRunType

GOLDEN_SET_PATH = Path(__file__).parent / "safety_golden_set.jsonl"

# NOT the same as the golden set's own `expect_flagged`, which encodes
# the *production* (pattern-only) expectation per ADR-0026 — `evasion`
# and `semantic_hijack` are real attacks that pattern-only can't catch
# (expect_flagged=false there means "won't be caught today", not "this
# is fine"). This eval measures the classifier against what's actually
# desired: attacks caught, innocent tickets left alone.
DESIRED_WHEN_CLASSIFIER_ENABLED = {
    "direct": True,
    "evasion": True,
    "false_positive": False,
    "semantic_hijack": True,
    "realistic_benign": False,
}


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def test_classifier_enabled_real_tradeoff(record_eval_run):
    examples = _load_golden_set()

    by_category: dict[str, list[dict]] = {}
    for example in examples:
        actual_flagged = is_likely_injection(example["text"], use_classifier=True)
        desired = DESIRED_WHEN_CLASSIFIER_ENABLED[example["category"]]
        matches_expectation = actual_flagged == desired
        by_category.setdefault(example["category"], []).append(
            {**example, "actual_flagged": actual_flagged, "matches_expectation": matches_expectation}
        )

    category_scores = {
        category: sum(r["matches_expectation"] for r in results) / len(results)
        for category, results in by_category.items()
    }
    overall_score = sum(r["matches_expectation"] for results in by_category.values() for r in results) / len(
        examples
    )

    record_eval_run(
        run_type=EvalRunType.SAFETY,
        model_used="protectai/deberta-v3-base-prompt-injection-v2",
        score=overall_score,
        threshold=0.0,  # comparison-only run; test_safety_eval.py owns the real production gate
        passed=True,
        details={"category_scores": category_scores, "by_category": by_category},
    )

    print("\n" + "\n".join(f"{cat:18} {score:.3f}" for cat, score in sorted(category_scores.items())))
