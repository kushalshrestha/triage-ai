"""A first, small sanity-check on the groundedness judge (see ADR-0009)
— project-brief.md's review notes flag that an LLM judge needs its own
reliability check before being trusted. This is two hand-crafted
examples, not the full "run twice on 10 examples, check stability"
study that note calls for (tracked as an open question in
ai-architecture.md). Real Ollama call.
"""
from app.agent.judge import PROMPT_VERSION, assess_groundedness
from app.config import get_settings
from app.models import EvalRunType

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


def _record(record_eval_run, name: str, passed: bool) -> None:
    record_eval_run(
        run_type=EvalRunType.FAITHFULNESS,
        prompt_version=PROMPT_VERSION,
        model_used=f"ollama/{get_settings().ollama_model_name}",
        score=1.0 if passed else 0.0,
        threshold=1.0,
        passed=passed,
        details={"example": name},
    )


def test_grounded_reply_passes(record_eval_run):
    grounded, _raw = assess_groundedness(GROUNDED_REPLY, CONTEXT)
    _record(record_eval_run, "grounded_reply", grounded is True)
    assert grounded is True


def test_hallucinated_reply_fails(record_eval_run):
    grounded, _raw = assess_groundedness(HALLUCINATED_REPLY, CONTEXT)
    _record(record_eval_run, "hallucinated_reply", grounded is False)
    assert grounded is False
