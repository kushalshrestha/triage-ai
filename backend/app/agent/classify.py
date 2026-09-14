"""Routine ticket classification via the local Ollama model (see
ADR-0008). Informational only — it does not drive auto-respond/
draft-for-review/escalate routing, which comes from RAG retrieval
similarity instead (see app/agent/orchestrator.py).
"""
from app.agent.ollama_client import generate

DEFAULT_CATEGORY = "bug"

_PROMPT_TEMPLATE = """Classify the support ticket below into exactly one category. \
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


def classify_ticket(text: str) -> str:
    raw = generate(_PROMPT_TEMPLATE.format(text=text))
    return _match_category(raw)


def _match_category(raw: str) -> str:
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
    return DEFAULT_CATEGORY
