from app.guardrails.pii import contains_pii, redact_pii


def test_redacts_email():
    text = "Please contact me at jane.doe@example.com about this."
    redacted = redact_pii(text)
    assert "jane.doe@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted


def test_redacts_phone_number():
    text = "Call me back at 555-867-5309 when you can."
    redacted = redact_pii(text)
    assert "555-867-5309" not in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_redacts_credit_card_like_number():
    text = "My card number is 4111 1111 1111 1111, please refund it."
    redacted = redact_pii(text)
    assert "4111 1111 1111 1111" not in redacted
    assert "[REDACTED_CARD]" in redacted


def test_leaves_normal_ticket_text_untouched():
    text = "My login keeps failing after the last password reset."
    assert redact_pii(text) == text


def test_contains_pii_true_for_email():
    assert contains_pii("reach me at test@example.com") is True


def test_contains_pii_false_for_normal_text():
    assert contains_pii("the app crashes on upload") is False
