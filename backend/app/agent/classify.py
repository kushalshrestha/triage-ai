"""Routine ticket classification (see ADR-0008, ADR-0022, ADR-0023).
Informational only — it does not drive auto-respond/draft-for-review/
escalate routing, which comes from RAG retrieval similarity instead
(see app/agent/orchestrator.py).

`classify_ticket(text, provider=...)` — `provider` defaults to
`"ollama"` (free, local); `"claude"` exists for the real accuracy/
latency comparison in
`tests/evals/test_classification_provider_comparison_eval.py`
(ADR-0022) — measured, not assumed, that routing this routine task to
the cheap local model isn't quietly costing real accuracy. Used only
by evals; production doesn't call this directly.

`classify_ticket_with_fallback(text)` — what
`app/agent/orchestrator.py` actually calls (ADR-0023). ADR-0022 found
Ollama's misses aren't random: it sometimes returns a bare word (e.g.
"support") that isn't one of the 4 valid categories, a self-detecting
failure. This tries Ollama first and only calls Claude for that one
ticket when Ollama's own output didn't parse — most tickets stay free,
some pay Claude's cost, informed by which one Ollama itself signaled
it couldn't confidently answer.
"""
import logging
from typing import Literal

from anthropic import Anthropic

from app.agent.ollama_client import generate
from app.config import get_settings

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
DEFAULT_CATEGORY = "bug"
CATEGORIES = ("billing", "bug", "account", "feature_request")

ClassificationProvider = Literal["ollama", "claude"]

_OLLAMA_PROMPT_TEMPLATE = """Classify the support ticket below into exactly one category. \
Respond with ONLY the category word, nothing else.

Categories:
- billing: charges, refunds, payments, subscriptions, invoices
- bug: something is broken, crashing, not working, stuck, an error
- account: login, password, profile, or account/email settings
- feature_request: a request to add or change a product feature

Examples:
Ticket: "I was charged twice this month"
Category: billing

Ticket: "The app crashes when I upload a photo"
Category: bug

Ticket: "How do I change my account email?"
Category: account

Ticket: "Can you add dark mode?"
Category: feature_request

Now classify this ticket:
Ticket: "{text}"
Category:"""

_CLAUDE_SYSTEM_PROMPT = (
    "Classify the support ticket into exactly one category using the "
    "classify_ticket tool.\n\n"
    "Categories:\n"
    "- billing: charges, refunds, payments, subscriptions, invoices\n"
    "- bug: something is broken, crashing, not working, stuck, an error\n"
    "- account: login, password, profile, or account/email settings\n"
    "- feature_request: a request to add or change a product feature"
)

_CLASSIFY_TOOL = {
    "name": "classify_ticket",
    "description": "Classify a support ticket into exactly one category.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": list(CATEGORIES),
                "description": "The single best-fitting category for this ticket.",
            }
        },
        "required": ["category"],
    },
}


def classify_ticket(text: str, provider: ClassificationProvider = "ollama") -> str:
    if provider == "claude":
        return _classify_ticket_claude(text)
    return _classify_ticket_ollama(text)


def _classify_ticket_ollama(text: str) -> str:
    raw = generate(_OLLAMA_PROMPT_TEMPLATE.format(text=text))
    return _match_category(raw) or DEFAULT_CATEGORY


def _match_category(raw: str) -> str | None:
    # A rambling model can mention multiple category words while
    # explaining itself before giving its actual answer — anchor on
    # whatever follows its last "category:" line (matching the prompt's
    # own requested format) rather than searching the whole response.
    if "category:" in raw:
        raw = raw.rsplit("category:", 1)[1]

    if "feature" in raw:
        return "feature_request"
    for category in ("billing", "bug", "account"):
        if category in raw:
            return category
    # None, not DEFAULT_CATEGORY — distinguishes "Ollama gave an
    # unparseable answer" (a real, diagnosed failure, ADR-0022) from
    # "Ollama confidently said bug", which matters for
    # classify_ticket_with_fallback() (ADR-0023) below.
    return None


def classify_ticket_with_fallback(text: str) -> tuple[str, bool]:
    """Production path (ADR-0023): try Ollama; if its raw output
    doesn't parse into a valid category, fall back to Claude for just
    this ticket rather than silently defaulting. Returns
    `(category, used_claude_fallback)` so the caller can track the
    real model usage/cost accurately — a fallback call is a real
    Claude API call even when it doesn't lead to a drafted reply.
    """
    raw = generate(_OLLAMA_PROMPT_TEMPLATE.format(text=text))
    category = _match_category(raw)
    if category is not None:
        return category, False

    try:
        return _classify_ticket_claude(text), True
    except Exception:
        logger.exception("Claude classification fallback failed; using default category")
        return DEFAULT_CATEGORY, True


def _classify_ticket_claude(text: str) -> str:
    # Forced tool-use with an enum-constrained field — schema-guaranteed
    # valid output, not prompt-engineered text parsing (see ADR-0022 for
    # why this matters for a fair comparison against Ollama's approach).
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.claude_model_name,
        max_tokens=50,
        system=_CLAUDE_SYSTEM_PROMPT,
        tools=[_CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "classify_ticket"},
        messages=[{"role": "user", "content": f'Ticket: "{text}"'}],
    )
    tool_use_block = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        return DEFAULT_CATEGORY
    category = tool_use_block.input.get("category")
    return category if category in CATEGORIES else DEFAULT_CATEGORY
