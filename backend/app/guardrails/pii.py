"""Input guardrail: redacts likely PII from ticket text before it
reaches any model call or log line.

Deliberately simple to start (pattern-based), same philosophy as
injection.py — swap for a classifier later, keep the function's
contract stable: string in, string out.
"""
import re

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]?){13,16}\b")

_PATTERNS = {
    "email": EMAIL_PATTERN,
    "credit_card": CREDIT_CARD_PATTERN,
    "phone": PHONE_PATTERN,
}


def contains_pii(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PATTERNS.values())


def redact_pii(text: str) -> str:
    # Order matters: check the more specific credit-card pattern before
    # phone, since a 16-digit run would otherwise partially match phone.
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = CREDIT_CARD_PATTERN.sub("[REDACTED_CARD]", text)
    text = PHONE_PATTERN.sub("[REDACTED_PHONE]", text)
    return text
