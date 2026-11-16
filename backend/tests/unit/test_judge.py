"""Pure failure-handling and provider-dispatch logic for
assess_groundedness, mocking the model calls — real-model behavior is
covered separately by tests/evals/test_groundedness_eval.py and
tests/evals/test_groundedness_provider_comparison_eval.py (ADR-0029).
This file didn't exist before ADR-0028: judge.py had no unit tests at
all, only the real-model eval.
"""
from types import SimpleNamespace
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


def _mock_claude_client(tool_input: dict) -> MagicMock:
    tool_use_block = SimpleNamespace(type="tool_use", input=tool_input)
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=50, output_tokens=5),
        content=[tool_use_block],
    )
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_claude_provider_dispatches_to_claude_not_ollama(monkeypatch):
    ollama_mock = MagicMock(return_value="answer: yes")
    monkeypatch.setattr(judge, "generate", ollama_mock)
    monkeypatch.setattr(
        judge, "Anthropic", MagicMock(return_value=_mock_claude_client({"grounded": True}))
    )

    assess_groundedness("Some reply.", ["Some context."], provider="claude")

    ollama_mock.assert_not_called()


def test_claude_grounded_verdict_parses(monkeypatch):
    monkeypatch.setattr(
        judge, "Anthropic", MagicMock(return_value=_mock_claude_client({"grounded": True}))
    )

    grounded, raw = assess_groundedness("Some reply.", ["Some context."], provider="claude")

    assert grounded is True
    assert raw == "True"


def test_claude_ungrounded_verdict_parses(monkeypatch):
    monkeypatch.setattr(
        judge, "Anthropic", MagicMock(return_value=_mock_claude_client({"grounded": False}))
    )

    grounded, _raw = assess_groundedness("Some reply.", ["Some context."], provider="claude")

    assert grounded is False


def test_claude_missing_tool_call_treated_as_not_grounded(monkeypatch):
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=50, output_tokens=0), content=[]
    )
    monkeypatch.setattr(judge, "Anthropic", MagicMock(return_value=client))

    grounded, raw = assess_groundedness("Some reply.", ["Some context."], provider="claude")

    assert grounded is False
    assert raw == "(no tool call)"
