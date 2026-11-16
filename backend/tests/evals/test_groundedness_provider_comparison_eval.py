"""Groundedness judge model comparison (ADR-0029) — the deferred
follow-up the capability roadmap named after ADR-0020 measured a real
reliability ceiling on Ollama (`reliable_accuracy=0.636`): try Claude
against the same golden set, with the same "run it twice" reliability
methodology (project-brief.md's literal ask), not just single-pass
accuracy like the classification provider comparison (ADR-0022) —
reliability, not raw accuracy, is the open question here. Real Claude
calls, hence tests/evals with @pytest.mark.costly, not tests/integration.
"""
import json
from pathlib import Path

import pytest

from app.agent.judge import PROMPT_VERSION, assess_groundedness
from app.config import get_settings
from app.models import EvalRunType

GOLDEN_SET_PATH = Path(__file__).parent / "groundedness_golden_set.jsonl"
RUNS_PER_EXAMPLE = 2  # same convention as test_groundedness_eval.py


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _score_provider(provider: str, golden_set: list[dict]) -> dict:
    per_example = []
    for example in golden_set:
        verdicts = [
            assess_groundedness(example["reply"], example["context"], provider=provider)[0]
            for _ in range(RUNS_PER_EXAMPLE)
        ]
        consistent = len(set(verdicts)) == 1
        correct = consistent and verdicts[0] == example["expected_grounded"]
        per_example.append(
            {"category": example["category"], "verdicts": verdicts, "consistent": consistent, "correct": correct}
        )

    consistency_rate = sum(e["consistent"] for e in per_example) / len(per_example)
    reliable_accuracy = sum(e["correct"] for e in per_example) / len(per_example)
    return {
        "consistency_rate": consistency_rate,
        "reliable_accuracy": reliable_accuracy,
        "per_example": per_example,
    }


@pytest.mark.costly
def test_ollama_vs_claude_groundedness_reliability(record_eval_run):
    golden_set = _load_golden_set()
    settings = get_settings()

    ollama_result = _score_provider("ollama", golden_set)
    claude_result = _score_provider("claude", golden_set)

    for provider, model_used, result in (
        ("ollama", f"ollama/{settings.ollama_model_name}", ollama_result),
        ("claude", f"claude/{settings.claude_model_name}", claude_result),
    ):
        for metric in ("consistency_rate", "reliable_accuracy"):
            record_eval_run(
                run_type=EvalRunType.FAITHFULNESS,
                prompt_version=PROMPT_VERSION,
                model_used=model_used,
                score=result[metric],
                threshold=0.0,  # comparison-only run; test_groundedness_eval.py owns the real gating threshold
                passed=True,
                details={
                    "metric": metric,
                    "provider": provider,
                    "runs_per_example": RUNS_PER_EXAMPLE,
                    "golden_set_size": len(golden_set),
                    "examples": result["per_example"],
                },
            )

    print(
        f"\nOllama: consistency_rate={ollama_result['consistency_rate']:.3f}, "
        f"reliable_accuracy={ollama_result['reliable_accuracy']:.3f}\n"
        f"Claude: consistency_rate={claude_result['consistency_rate']:.3f}, "
        f"reliable_accuracy={claude_result['reliable_accuracy']:.3f}"
    )
