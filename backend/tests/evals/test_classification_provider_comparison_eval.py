"""Ollama-vs-Claude classification accuracy/latency comparison (ADR-0022)
— project-brief.md's "Model routing" capability claims the Ollama/
Claude split is "backed by measured cost/latency/accuracy." Cost and
latency were: `scripts/cost_report.py` (ADR-0010). Accuracy, for the
actual routing split, never was — this is that measurement. Real
Claude calls, hence tests/evals with @pytest.mark.costly, not
tests/integration.
"""
import json
import time
from pathlib import Path

import pytest

from app.agent.classify import PROMPT_VERSION, classify_ticket
from app.config import get_settings
from app.models import EvalRunType

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.jsonl"
CLAUDE_ACCURACY_THRESHOLD = 0.8


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _score_provider(provider: str, golden_set: list[dict]) -> tuple[float, float, int]:
    correct = 0
    latencies_ms = []
    for example in golden_set:
        start = time.monotonic()
        predicted = classify_ticket(example["ticket_text"], provider=provider)
        latencies_ms.append((time.monotonic() - start) * 1000)
        correct += predicted == example["expected_label"]
    accuracy = correct / len(golden_set)
    avg_latency_ms = sum(latencies_ms) / len(latencies_ms)
    return accuracy, avg_latency_ms, correct


@pytest.mark.costly
def test_ollama_vs_claude_classification_accuracy(record_eval_run):
    golden_set = _load_golden_set()
    settings = get_settings()

    ollama_accuracy, ollama_latency_ms, ollama_correct = _score_provider("ollama", golden_set)
    claude_accuracy, claude_latency_ms, claude_correct = _score_provider("claude", golden_set)

    record_eval_run(
        run_type=EvalRunType.CLASSIFICATION,
        prompt_version=PROMPT_VERSION,
        model_used=f"ollama/{settings.ollama_model_name}",
        score=ollama_accuracy,
        threshold=0.6,  # matches test_classification_eval.py's real, measured baseline
        passed=ollama_accuracy >= 0.6,
        details={
            "golden_set_size": len(golden_set),
            "correct": ollama_correct,
            "avg_latency_ms": ollama_latency_ms,
        },
    )
    record_eval_run(
        run_type=EvalRunType.CLASSIFICATION,
        prompt_version=PROMPT_VERSION,
        model_used=f"claude/{settings.claude_model_name}",
        score=claude_accuracy,
        threshold=CLAUDE_ACCURACY_THRESHOLD,
        passed=claude_accuracy >= CLAUDE_ACCURACY_THRESHOLD,
        details={
            "golden_set_size": len(golden_set),
            "correct": claude_correct,
            "avg_latency_ms": claude_latency_ms,
        },
    )

    assert claude_accuracy >= CLAUDE_ACCURACY_THRESHOLD, (
        f"Claude classification accuracy {claude_accuracy:.2f} fell below "
        f"threshold {CLAUDE_ACCURACY_THRESHOLD}"
    )
    # A real, honest sanity check, not a redundant assertion: if the
    # paid option were ever *worse* than the free one, that's a red
    # flag worth failing loudly on, not silently accepting.
    assert claude_accuracy >= ollama_accuracy, (
        f"Claude ({claude_accuracy:.2f}) scored worse than Ollama "
        f"({ollama_accuracy:.2f}) — unexpected, investigate before trusting either number."
    )
