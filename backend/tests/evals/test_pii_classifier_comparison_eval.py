"""Pattern-only fallback baseline (`use_classifier=False`) — what
`redact_pii`/`contains_pii` regress to if the Presidio classifier ever
needs to be disabled (unreachable model, resource constraints, etc.).
`test_pii_redaction_eval.py` tests the real production default
(classifier enabled); this file documents what's lost without it —
`ner_gap` drops to the pre-ADR-0032 0% ceiling.

Not marked @pytest.mark.costly — no Claude API cost, just local
models (same resource class as the cross-encoder reranker and the
Phase 28 injection classifier, both already used freely in
tests/evals).
"""
import json
from pathlib import Path

from app.guardrails.pii import contains_pii
from app.models import EvalRunType

GOLDEN_SET_PATH = Path(__file__).parent / "pii_golden_set.jsonl"


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def test_pattern_only_fallback_baseline(record_eval_run):
    examples = _load_golden_set()

    by_category: dict[str, list[dict]] = {}
    for example in examples:
        actual_flagged = contains_pii(example["text"], use_classifier=False)
        matches_expectation = actual_flagged == example["expect_flagged"]
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
        model_used="none",  # pattern-only, no model call
        score=overall_score,
        threshold=0.0,  # documentation-only run; test_pii_redaction_eval.py owns the real gate
        passed=True,
        details={"category_scores": category_scores, "by_category": by_category},
    )

    print("\n" + "\n".join(f"{cat:18} {score:.3f}" for cat, score in sorted(category_scores.items())))
