"""Pure failure-handling logic for assess_groundedness, mocking the
Ollama call — real-model behavior is covered separately by
tests/evals/test_groundedness_eval.py. This file didn't exist before
ADR-0028: judge.py had no unit tests at all, only the real-model eval.
"""
from unittest.mock import MagicMock

import httpx

from app.agent import judge
from app.agent.judge import assess_groundedness


def test_unreachable_ollama_is_treated_as_not_grounded(monkeypatch):
    """ADR-0028: an unreachable/timed-out judge must fail safe (treated
    as not grounded, downgrading auto_respond downstream) rather than
    raising and crashing the whole triage request.
    """
    monkeypatch.setattr(
        judge, "generate", MagicMock(side_effect=httpx.ConnectError("Ollama down"))
    )

    grounded, raw = assess_groundedness("Some reply.", ["Some context."])

    assert grounded is False
    assert "groundedness check failed" in raw


def test_grounded_reply_passes(monkeypatch):
    monkeypatch.setattr(judge, "generate", MagicMock(return_value="answer: yes"))

    grounded, raw = assess_groundedness("Some reply.", ["Some context."])

    assert grounded is True
    assert raw == "answer: yes"
