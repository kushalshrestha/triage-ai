"""Groundedness judge reliability study (ADR-0020).

project-brief.md's review notes flagged early on that an LLM judge
needs its own reliability check — "run it twice on ~10 examples,
confirm stable scores" — before being trusted for regression gating.
This went from a hypothetical open question to a real, reproduced
finding during Phase 16 (ADR-0019): a single hand-picked eval example
passed 5/5 locally (arm64) but failed once in CI (x86_64) at
temperature 0, and a follow-up attempt at a "starker" example turned
out to be consistently wrong in a different way — the judge doesn't
reliably penalize a reply checked against totally irrelevant context,
only apparent contradiction. Both failure modes are now golden-set
categories (`irrelevant_context`, `adjacent_wrong_topic`) instead of
one-off examples, and this file measures across all of them with
aggregate scoring, not individual hard asserts — the convention every
other eval in this project already follows (testing-strategy.md layer
3), which the old version of this file didn't.
"""
import json
from pathlib import Path

from app.agent.judge import PROMPT_VERSION, assess_groundedness
from app.config import get_settings
from app.models import EvalRunType

GOLDEN_SET_PATH = Path(__file__).parent / "groundedness_golden_set.jsonl"
RUNS_PER_EXAMPLE = 2  # project-brief.md's literal ask: "run it twice"

# Thresholds set from real measurement (ADR-0020), not guessed in
# advance — same convention as every other eval in this project.
# Measured for the current prompt (v1): consistency_rate=1.0 (perfect
# same-environment stability at temperature 0 — this metric can't
# detect the *cross-architecture* nondeterminism found via the real
# CI incident that motivated this file, only same-run repeatability),
# reliable_accuracy=0.636 (7/11) — the best of four prompt variants
# tried (see ADR-0020's Alternatives; three rewrites all measured
# worse: 0.45, 0.45, 0.55). That's a real, honestly-reported capability
# ceiling for this local 1B model on this task, not a prompt-wording
# bug — kept as PROMPT_VERSION "v1", unchanged. Thresholds below give
# headroom for one example flipping (a known, documented risk) without
# being toothless against a real regression.
CONSISTENCY_THRESHOLD = 0.8
RELIABLE_ACCURACY_THRESHOLD = 0.5


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def test_groundedness_judge_reliability(record_eval_run):
    examples = _load_golden_set()
    per_example = []

    for example in examples:
        verdicts = [
            assess_groundedness(example["reply"], example["context"])[0]
            for _ in range(RUNS_PER_EXAMPLE)
        ]
        consistent = len(set(verdicts)) == 1
        # Disagreement always counts against reliability — an
        # inconsistent verdict on a case that matters isn't "half
        # credit," it's exactly the thing this study exists to catch.
        correct = consistent and verdicts[0] == example["expected_grounded"]
        per_example.append(
            {
                "category": example["category"],
                "verdicts": verdicts,
                "consistent": consistent,
                "correct": correct,
            }
        )

    consistency_rate = sum(e["consistent"] for e in per_example) / len(per_example)
    reliable_accuracy = sum(e["correct"] for e in per_example) / len(per_example)

    model_used = f"ollama/{get_settings().ollama_model_name}"
    record_eval_run(
        run_type=EvalRunType.FAITHFULNESS,
        prompt_version=PROMPT_VERSION,
        model_used=model_used,
        score=consistency_rate,
        threshold=CONSISTENCY_THRESHOLD,
        passed=consistency_rate >= CONSISTENCY_THRESHOLD,
        details={"metric": "consistency_rate", "runs_per_example": RUNS_PER_EXAMPLE, "examples": per_example},
    )
    record_eval_run(
        run_type=EvalRunType.FAITHFULNESS,
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
