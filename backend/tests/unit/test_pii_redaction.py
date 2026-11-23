"""`redact_pii`/`contains_pii`'s dispatch logic is pure/deterministic
once the classifier call is mocked — see ADR-0032. Real-model behavior
(does Presidio actually catch names/SSNs/addresses, and the real
false-positive rate on realistic ticket content) is covered separately
by tests/evals/test_pii_redaction_eval.py and
tests/evals/test_pii_classifier_comparison_eval.py.

Pattern-only tests below pass `use_classifier=False` explicitly —
they're testing the regex behavior specifically, decoupled from
whatever the function's own default is.
"""
from unittest.mock import MagicMock

from app.guardrails import pii
from app.guardrails.pii import contains_pii, redact_pii


def test_redacts_email():
    text = "Please contact me at jane.doe@example.com about this."
    redacted = redact_pii(text, use_classifier=False)
    assert "jane.doe@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted


def test_redacts_phone_number():
    text = "Call me back at 555-867-5309 when you can."
    redacted = redact_pii(text, use_classifier=False)
    assert "555-867-5309" not in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_redacts_credit_card_like_number():
    text = "My card number is 4111 1111 1111 1111, please refund it."
    redacted = redact_pii(text, use_classifier=False)
    assert "4111 1111 1111 1111" not in redacted
    assert "[REDACTED_CARD]" in redacted


def test_leaves_normal_ticket_text_untouched():
    text = "My login keeps failing after the last password reset."
    assert redact_pii(text, use_classifier=False) == text


def test_contains_pii_true_for_email():
    assert contains_pii("reach me at test@example.com", use_classifier=False) is True


def test_contains_pii_false_for_normal_text():
    assert contains_pii("the app crashes on upload", use_classifier=False) is False


def test_classifier_enabled_by_default(monkeypatch):
    """ADR-0032: unlike the injection classifier (ADR-0031, opt-in),
    the PII classifier defaults to enabled — real measurement found a
    much smaller, much milder-consequence false-positive rate here.
    """
    classifier_mock = MagicMock(return_value=True)
    monkeypatch.setattr(pii, "_classifier_detects", classifier_mock)
    text = "Hi, this is John Smith, my order never arrived."
    assert contains_pii(text) is True
    classifier_mock.assert_called_once()


def test_classifier_can_be_disabled_explicitly(monkeypatch):
    classifier_mock = MagicMock(return_value=True)
    monkeypatch.setattr(pii, "_classifier_detects", classifier_mock)
    text = "Hi, this is John Smith, my order never arrived."
    assert contains_pii(text, use_classifier=False) is False
    classifier_mock.assert_not_called()


def test_pattern_match_short_circuits_without_calling_classifier(monkeypatch):
    classifier_mock = MagicMock(return_value=False)
    monkeypatch.setattr(pii, "_classifier_detects", classifier_mock)
    text = "reach me at test@example.com"
    assert contains_pii(text) is True
    classifier_mock.assert_not_called()


def test_redact_applies_classifier_after_patterns_by_default(monkeypatch):
    monkeypatch.setattr(pii, "_classifier_redact", MagicMock(return_value="[REDACTED_PERSON] text"))
    text = "John Smith text"
    assert redact_pii(text) == "[REDACTED_PERSON] text"


def test_classifier_failure_falls_back_to_pattern_only(monkeypatch):
    """ADR-0032/ADR-0028: a classifier call that raises must not crash
    the whole check — falls back to the pattern-only result.
    """
    monkeypatch.setattr(
        pii, "_get_analyzer", MagicMock(side_effect=RuntimeError("model unavailable"))
    )
    assert contains_pii("My login keeps failing.") is False
    assert redact_pii("My login keeps failing.") == "My login keeps failing."
    assert contains_pii("reach me at test@example.com") is True
