"""LLM-as-judge for draft quality (see ADR-0025) — an evals-layer
metric, not a production guardrail. Unlike `judge.py`'s groundedness
check (wired into `orchestrator.py`, affects real routing), this rates
whether a draft is actually *good* — helpful, appropriately toned,
complete — not just grounded. Measured offline over a golden set,
per project-brief.md's "Golden dataset + offline metrics" capability
and `docs/testing-strategy.md`'s long-stated (never-built) intent:
"LLM-as-judge quality >= 4/5."
"""
from typing import Literal

from anthropic import Anthropic

from app.agent.ollama_client import generate
from app.config import get_settings

PROMPT_VERSION = "v1"
RATINGS = (1, 2, 3, 4, 5)

QualityJudgeProvider = Literal["ollama", "claude"]

_RUBRIC = (
    "1 = does not address the question\n"
    "2 = confusing or rude\n"
    "3 = adequate but flawed\n"
    "4 = clear and professional\n"
    "5 = excellent"
)

# Short and direct, deliberately — ADR-0009/ADR-0020 both found this
# specific local model responds unpredictably, sometimes worse, to
# longer or more elaborate instructions. Same Context/Reply/Question
# shape as judge.py::assess_groundedness, which already works at this
# length for this model.
_OLLAMA_PROMPT_TEMPLATE = """Context: {context}

Ticket: {ticket_text}

Reply: {reply}

Rate the reply's quality as a customer support response, from 1 to 5:
""" + _RUBRIC + """

Respond with ONLY the number.

Rating:"""

_CLAUDE_SYSTEM_PROMPT = (
    "Rate a customer support reply's quality from 1 to 5 using the "
    "submit_quality_rating tool.\n\n" + _RUBRIC
)

_QUALITY_TOOL = {
    "name": "submit_quality_rating",
    "description": "Submit a 1-5 quality rating for a customer support reply.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rating": {
                "type": "integer",
                "enum": list(RATINGS),
                "description": "The quality rating, 1 (worst) to 5 (best).",
            }
        },
        "required": ["rating"],
    },
}


def assess_draft_quality(
    reply_text: str,
    ticket_subject: str,
    ticket_body: str,
    context_chunks: list[str],
    provider: QualityJudgeProvider = "ollama",
) -> tuple[int | None, str]:
    """Returns (rating, raw_judge_output). rating is None when the raw
    output doesn't parse to a valid 1-5 value — the same honest-
    nullable pattern as classify.py::_match_category (ADR-0022) rather
    than silently defaulting to some rating.
    """
    ticket_text = f"{ticket_subject}\n{ticket_body}"
    context = "\n\n---\n\n".join(context_chunks) if context_chunks else "(no context provided)"
    if provider == "claude":
        return _assess_quality_claude(reply_text, ticket_text, context)
    return _assess_quality_ollama(reply_text, ticket_text, context)


def _assess_quality_ollama(reply_text: str, ticket_text: str, context: str) -> tuple[int | None, str]:
    raw = generate(
        _OLLAMA_PROMPT_TEMPLATE.format(context=context, ticket_text=ticket_text, reply=reply_text)
    )
    return _parse_rating(raw), raw


def _parse_rating(raw: str) -> int | None:
    if "rating:" in raw:
        raw = raw.rsplit("rating:", 1)[1]
    for token in raw.replace(".", " ").split():
        if token.isdigit() and int(token) in RATINGS:
            return int(token)
    return None


def _assess_quality_claude(reply_text: str, ticket_text: str, context: str) -> tuple[int | None, str]:
    # Forced tool-use with an enum-constrained field — schema-guaranteed
    # valid output, same fairness rationale as ADR-0022's classification
    # comparison (Ollama's free-text parsing isn't an unfair disadvantage,
    # Claude's structured output isn't an unfair advantage disconnected
    # from real rating quality).
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.claude_model_name,
        max_tokens=50,
        system=_CLAUDE_SYSTEM_PROMPT,
        tools=[_QUALITY_TOOL],
        tool_choice={"type": "tool", "name": "submit_quality_rating"},
        messages=[
            {
                "role": "user",
                "content": f'Context: "{context}"\n\nTicket: "{ticket_text}"\n\nReply: "{reply_text}"',
            }
        ],
    )
    tool_use_block = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        return None, "(no tool call)"
    rating = tool_use_block.input.get("rating")
    return (rating if rating in RATINGS else None), str(rating)
