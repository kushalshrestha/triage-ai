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

# Demonstrates why ADR-0019 checks groundedness against only the chunks
# a draft actually cites, not the whole retrieved pool: REFUND_CHUNK and
# CANCELLATION_CHUNK are on different topics; CANCELLATION_REPLY is
# genuinely grounded in CANCELLATION_CHUNK, but if a draft mis-cited
# REFUND_CHUNK instead, checking against the whole pool would still pass
# it (CANCELLATION_CHUNK is right there supporting it) — masking the bad
# citation entirely.
REFUND_CHUNK = (
    "Refunds for subscription charges are processed within 5-7 business "
    "days back to the original payment method."
)
CANCELLATION_CHUNK = (
    "To cancel your subscription, go to Billing > Subscription and click "
    "'Cancel Plan'. Cancellation takes effect at the end of the current "
    "billing period."
)
CANCELLATION_REPLY = (
    "To cancel your subscription, go to Billing > Subscription and click "
    "'Cancel Plan'; it will take effect at the end of your current "
    "billing period."
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


def test_reply_grounded_against_full_pool_when_correct_chunk_present(record_eval_run):
    """Baseline: today's pre-ADR-0019 behavior — checking against the
    whole retrieved pool passes when a supporting chunk is anywhere in
    it, regardless of which chunk was actually cited.
    """
    grounded, _raw = assess_groundedness(CANCELLATION_REPLY, [REFUND_CHUNK, CANCELLATION_CHUNK])
    _record(record_eval_run, "full_pool_with_supporting_chunk_present", grounded is True)
    assert grounded is True


def test_reply_fails_when_checked_against_a_misleading_citation(record_eval_run):
    """ADR-0019: the same reply, checked against only a (deliberately
    wrong) cited chunk, correctly fails — proving citation-scoped
    checking catches a "right answer, misleading citation" case that
    whole-pool checking (test above) would silently pass.
    """
    grounded, _raw = assess_groundedness(CANCELLATION_REPLY, [REFUND_CHUNK])
    _record(record_eval_run, "cited_chunk_only_misleading_citation", grounded is False)
    assert grounded is False
