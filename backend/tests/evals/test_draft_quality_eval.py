"""Draft-quality judge reliability study (ADR-0025) — project-brief.md's
"Golden dataset + offline metrics" names "LLM-as-judge for draft
quality" as a capability; nothing measured it until now.
`docs/testing-strategy.md` has said "LLM-as-judge quality >= 4/5"
since early in this project and it was never built.

Same "run it twice, measure consistency and accuracy" structure as
ADR-0020's groundedness-judge study — a graded 1-5 rating is a
plausibly *harder* task for the local 1B model than that binary
check, which already showed a real reliability ceiling. Measured, not
assumed.
"""
import json
from pathlib import Path

from app.agent.quality import PROMPT_VERSION, assess_draft_quality
from app.config import get_settings
from app.models import EvalRunType

GOLDEN_SET_PATH = Path(__file__).parent / "draft_quality_golden_set.jsonl"
RUNS_PER_EXAMPLE = 2  # same convention as ADR-0020: "run it twice"
RATING_TOLERANCE = 1  # a 1-5 quality judgment has legitimate subjective
# variance even between careful human raters — an exact-match bar
# would be unreasonably strict for a graded, not binary, judgment.

# Thresholds set from real measurement (ADR-0025), not guessed in
# advance — same convention as every eval in this project. Measured
# for Ollama: consistency_rate=1.0 (perfect same-environment
# stability), reliable_accuracy=0.917 (11/12) — genuinely better than
# the groundedness judge's 0.636 (ADR-0020), contradicting the prior
# expectation that a graded 1-5 task would be *harder* than a binary
# one. The one miss was a defensible disagreement (a graceful "we
# don't have that feature" decline, rated 5 for honesty/warmth here
# but 3 by the judge for not fulfilling the literal request) more than
# a clear model error. No Claude comparison needed — the contingency
# for one ("if Ollama shows a real ceiling") didn't trigger.
CONSISTENCY_THRESHOLD = 0.8
RELIABLE_ACCURACY_THRESHOLD = 0.75


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _run_reliability_study(provider: str) -> tuple[float, float, list[dict]]:
    examples = _load_golden_set()
    per_example = []

    for example in examples:
        ratings = [
            assess_draft_quality(
                example["reply"],
                example["ticket_subject"],
                example["ticket_body"],
                example["context"],
                provider=provider,
            )[0]
            for _ in range(RUNS_PER_EXAMPLE)
        ]
        consistent = len(set(ratings)) == 1 and ratings[0] is not None
        correct = (
            consistent
            and abs(ratings[0] - example["expected_rating"]) <= RATING_TOLERANCE
        )
        per_example.append(
            {
                "ticket_subject": example["ticket_subject"],
                "expected_rating": example["expected_rating"],
                "ratings": ratings,
                "consistent": consistent,
                "correct": correct,
            }
        )

    consistency_rate = sum(e["consistent"] for e in per_example) / len(per_example)
    reliable_accuracy = sum(e["correct"] for e in per_example) / len(per_example)
    return consistency_rate, reliable_accuracy, per_example


def test_ollama_draft_quality_judge_reliability(record_eval_run, assert_no_regression):
    consistency_rate, reliable_accuracy, per_example = _run_reliability_study("ollama")

    model_used = f"ollama/{get_settings().ollama_model_name}"
    record_eval_run(
        run_type=EvalRunType.JUDGE,
        prompt_version=PROMPT_VERSION,
        model_used=model_used,
        score=consistency_rate,
        threshold=CONSISTENCY_THRESHOLD,
        passed=consistency_rate >= CONSISTENCY_THRESHOLD,
        details={"metric": "consistency_rate", "runs_per_example": RUNS_PER_EXAMPLE, "examples": per_example},
    )
    record_eval_run(
        run_type=EvalRunType.JUDGE,
        prompt_version=PROMPT_VERSION,
        model_used=model_used,
        score=reliable_accuracy,
        threshold=RELIABLE_ACCURACY_THRESHOLD,
        passed=reliable_accuracy >= RELIABLE_ACCURACY_THRESHOLD,
        details={"metric": "reliable_accuracy", "runs_per_example": RUNS_PER_EXAMPLE, "examples": per_example},
    )

    assert consistency_rate >= CONSISTENCY_THRESHOLD, (
        f"consistency_rate was {consistency_rate:.2f}, expected >= {CONSISTENCY_THRESHOLD}"
    )
    assert reliable_accuracy >= RELIABLE_ACCURACY_THRESHOLD, (
        f"reliable_accuracy was {reliable_accuracy:.2f}, expected >= {RELIABLE_ACCURACY_THRESHOLD}"
    )
    # Flat thresholds (above) catch an absolute floor; this (ADR-0024's
    # mechanism, reused here) catches a real regression against a
    # committed baseline even if it's still above that floor.
    assert_no_regression("judge", model_used, consistency_rate, metric="consistency_rate")
    assert_no_regression("judge", model_used, reliable_accuracy, metric="reliable_accuracy")
