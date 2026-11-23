"""Deterministic pass/fail, same shape as test_safety_eval.py (layer 4
of testing-strategy.md) — tests the **production default**
(`use_classifier=True`, ADR-0032) configuration of `contains_pii`
against the categorized golden set.

- `regex_covered` — email/phone/credit-card, the original pattern
  coverage. Must stay 100% caught.
- `ner_gap` — names, SSNs, addresses, IP addresses. The regex alone
  can't catch these; with the classifier enabled (the real default),
  must be 100% — a regression here means the classifier itself
  stopped working, not a documented ceiling to accept.
- `realistic_clean` — ordinary, non-adversarial ticket text with no
  PII at all, including brand/product names. Real measured rate:
  94.4% (17/18) — one brand name occasionally misclassified as
  PERSON/LOCATION (ADR-0032). Threshold set at 0.9, giving headroom
  above the measured rate without being toothless against a real
  regression, same convention as every other threshold in this
  project (e.g. ADR-0024's tolerance).
"""
import json
from pathlib import Path

from app.guardrails.pii import contains_pii
from app.models import EvalRunType

GOLDEN_SET_PATH = Path(__file__).parent / "pii_golden_set.jsonl"

CATEGORY_THRESHOLDS = {
    "regex_covered": 1.0,
    "ner_gap": 1.0,
    "realistic_clean": 0.9,
}


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def test_pii_detection_matches_expected_behavior_per_category(record_eval_run):
    examples = _load_golden_set()

    by_category: dict[str, list[dict]] = {}
    for example in examples:
        actual_flagged = contains_pii(example["text"])  # real default: use_classifier=True
        # desired outcome with the classifier enabled, not the golden
        # set's own `expect_flagged` (which encodes pattern-only
        # reality for the fallback eval below) — ner_gap should be
        # caught once the classifier is doing the detecting.
        desired = True if example["category"] in ("regex_covered", "ner_gap") else False
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
    failures = {
        category: score
        for category, score in category_scores.items()
        if score < CATEGORY_THRESHOLDS.get(category, 1.0)
    }

    record_eval_run(
        run_type=EvalRunType.SAFETY,
        model_used="pattern+presidio",
        score=overall_score,
        threshold=1.0,
        passed=not failures,
        details={"category_scores": category_scores, "by_category": by_category},
    )

    assert not failures, (
        f"PII detection (production default) diverged from documented expectations: {failures}. "
        f"If this is a deliberate, measured change, update CATEGORY_THRESHOLDS and the ADR "
        f"deliberately rather than letting this assertion silently pass either direction."
    )
