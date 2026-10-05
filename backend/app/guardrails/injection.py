"""Input guardrail: flags likely prompt-injection attempts in ticket text.

Deliberately simple to start (keyword/pattern based). Swap for a
classifier later, but keep this function's contract stable so the
unit tests below don't need to change: input string in, bool out.
"""

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore prior instructions",
    "disregard the above",
    "you are now",
    # Trailing colon required (ADR-0026): a bare "system prompt" false-
    # positives on innocent tickets mentioning a device's own prompt/UI
    # (e.g. "my thermostat's system prompt keeps asking for a PIN").
    "system prompt:",
    "act as if",
]


def is_likely_injection(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in INJECTION_PATTERNS)
