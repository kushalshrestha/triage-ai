"""Eval tests assert against a THRESHOLD over a fixed dataset, not exact
output — the model's classification can vary in wording/confidence
between runs, so 'accuracy >= 0.9 on the golden set' is the right bar,
not 'output == expected string'.

Run the full golden set nightly / pre-release. A small smoke subset
(first N rows) can run on every PR as a fast eval gate — wire that up
once the classifier call exists.
"""
import json
from pathlib import Path

import pytest

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.jsonl"
ACCURACY_THRESHOLD = 0.90


def load_golden_set():
    with open(GOLDEN_SET_PATH) as f:
        return [json.loads(line) for line in f]


@pytest.mark.skip(reason="Wire up once the classifier (Ollama routing) exists")
def test_classification_accuracy_meets_threshold():
    from app.agent.classify import classify_ticket  # implement in phase 2/4

    golden_set = load_golden_set()
    correct = 0
    for example in golden_set:
        predicted = classify_ticket(example["ticket_text"])
        if predicted == example["expected_label"]:
            correct += 1

    accuracy = correct / len(golden_set)
    assert accuracy >= ACCURACY_THRESHOLD, (
        f"Classification accuracy {accuracy:.2f} fell below "
        f"threshold {ACCURACY_THRESHOLD} — check for regressions "
        f"before merging."
    )
