"""A first, small sanity-check on the groundedness judge (see ADR-0009)
— project-brief.md's review notes flag that an LLM judge needs its own
reliability check before being trusted. This is two hand-crafted
examples, not the full "run twice on 10 examples, check stability"
study that note calls for (tracked as an open question in
ai-architecture.md). Real Ollama call.
"""
from app.agent.judge import assess_groundedness

CONTEXT = [
    "To reset your password, go to the login page and click 'Forgot "
    "password'. Enter your account email and we'll send a reset link "
    "that expires after one hour."
]

GROUNDED_REPLY = (
    "You can reset your password by clicking 'Forgot password' on the "
    "login page and entering your account email. The reset link will "
    "expire after one hour."
)

HALLUCINATED_REPLY = (
    "You can reset your password by calling our 24/7 phone support line "
    "at 1-800-555-0100 and a representative will reset it for you "
    "immediately over the phone."
)


def test_grounded_reply_passes():
    grounded, _raw = assess_groundedness(GROUNDED_REPLY, CONTEXT)
    assert grounded is True


def test_hallucinated_reply_fails():
    grounded, _raw = assess_groundedness(HALLUCINATED_REPLY, CONTEXT)
    assert grounded is False
