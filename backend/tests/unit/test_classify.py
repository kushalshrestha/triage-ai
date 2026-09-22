"""_match_category and classify_ticket_with_fallback's branching logic
are pure/deterministic once the model calls are mocked — see ADR-0022
(the "support" parse failure) and ADR-0023 (the fallback built on it).
"""
from unittest.mock import MagicMock

from app.agent import classify
from app.agent.classify import DEFAULT_CATEGORY, _match_category, classify_ticket_with_fallback


def test_match_category_matches_known_categories():
    assert _match_category("Category: billing") == "billing"
    assert _match_category("bug") == "bug"
    assert _match_category("this is a feature request") == "feature_request"


def test_match_category_returns_none_for_unparseable_input():
    # The real, diagnosed Ollama failure mode (ADR-0022): a bare word
    # that isn't one of the 4 valid categories.
    assert _match_category("support") is None
    assert _match_category("") is None


def test_fallback_uses_ollama_result_without_calling_claude(monkeypatch):
    monkeypatch.setattr(classify, "generate", MagicMock(return_value="category: billing"))
    claude_mock = MagicMock()
    monkeypatch.setattr(classify, "_classify_ticket_claude", claude_mock)

    category, used_fallback = classify_ticket_with_fallback("I was charged twice")

    assert category == "billing"
    assert used_fallback is False
    claude_mock.assert_not_called()


def test_fallback_calls_claude_when_ollama_output_is_unparseable(monkeypatch):
    monkeypatch.setattr(classify, "generate", MagicMock(return_value="support"))
    claude_mock = MagicMock(return_value="account")
    monkeypatch.setattr(classify, "_classify_ticket_claude", claude_mock)

    category, used_fallback = classify_ticket_with_fallback("some ambiguous ticket text")

    assert category == "account"
    assert used_fallback is True
    claude_mock.assert_called_once()


def test_fallback_defaults_when_claude_also_fails(monkeypatch):
    monkeypatch.setattr(classify, "generate", MagicMock(return_value="support"))
    monkeypatch.setattr(
        classify, "_classify_ticket_claude", MagicMock(side_effect=RuntimeError("API down"))
    )

    category, used_fallback = classify_ticket_with_fallback("some ambiguous ticket text")

    assert category == DEFAULT_CATEGORY
    # Still True — a real Claude call was attempted (and thus incurred
    # real latency/cost) even though it ultimately failed.
    assert used_fallback is True
