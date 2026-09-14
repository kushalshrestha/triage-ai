from anthropic import Anthropic

from app.config import get_settings
from app.models import Ticket

_SYSTEM_PROMPT = (
    "You are a customer support agent drafting a reply to a support ticket. "
    "Use ONLY the information in the provided context to answer. If the "
    "context doesn't contain enough information to fully answer the ticket, "
    "say so honestly rather than guessing. Be concise and professional."
)


def generate_draft(ticket: Ticket, context_chunks: list[str], account_context: dict) -> str:
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    context_block = (
        "\n\n---\n\n".join(context_chunks) if context_chunks else "(no relevant context found)"
    )
    user_message = (
        f"Customer account: {account_context['prior_ticket_count']} prior ticket(s), "
        f"account age {account_context['account_age_days']} day(s).\n\n"
        f"Context:\n{context_block}\n\n"
        f"Ticket subject: {ticket.subject}\n"
        f"Ticket body: {ticket.body}\n\n"
        f"Draft a reply."
    )

    message = client.messages.create(
        model=settings.claude_model_name,
        max_tokens=500,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text
