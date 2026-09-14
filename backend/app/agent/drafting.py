from dataclasses import dataclass

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.models import Ticket

PROMPT_VERSION = "v1"

_SYSTEM_PROMPT = (
    "You are a customer support agent drafting a reply to a support ticket. "
    "Use ONLY the information in the provided context to answer. If the "
    "context doesn't contain enough information to fully answer the ticket, "
    "say so honestly rather than guessing. Be concise and professional."
)

_DRAFT_TOOL = {
    "name": "submit_draft",
    "description": "Submit the drafted customer support reply.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply_text": {
                "type": "string",
                "description": "The drafted reply to send to the customer.",
            },
            "cited_chunk_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "0-based indices into the provided context chunks that this "
                    "reply is grounded in."
                ),
            },
        },
        "required": ["reply_text", "cited_chunk_indices"],
    },
}


class DraftOutput(BaseModel):
    reply_text: str
    cited_chunk_indices: list[int]


@dataclass
class ClaudeUsage:
    input_tokens: int
    output_tokens: int


class DraftSchemaError(Exception):
    """Claude's tool call was missing, malformed, or cited an
    out-of-range chunk index. Caught by the orchestrator to force an
    escalation instead of surfacing a broken draft — see ADR-0009.

    `usage` is attached when available (ADR-0010) — the Claude call
    still cost money even when its output failed validation, so the
    orchestrator can still record token counts on the escalated
    decision.
    """

    def __init__(self, message: str, usage: ClaudeUsage | None = None):
        super().__init__(message)
        self.usage = usage


def generate_draft(
    ticket: Ticket, context_chunks: list[str], account_context: dict
) -> tuple[DraftOutput, ClaudeUsage]:
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    context_block = (
        "\n\n---\n\n".join(f"[{i}] {chunk}" for i, chunk in enumerate(context_chunks))
        if context_chunks
        else "(no relevant context found)"
    )
    user_message = (
        f"Customer account: {account_context['prior_ticket_count']} prior ticket(s), "
        f"account age {account_context['account_age_days']} day(s).\n\n"
        f"Context (indexed):\n{context_block}\n\n"
        f"Ticket subject: {ticket.subject}\n"
        f"Ticket body: {ticket.body}\n\n"
        f"Call submit_draft with your reply."
    )

    message = client.messages.create(
        model=settings.claude_model_name,
        max_tokens=500,
        system=_SYSTEM_PROMPT,
        tools=[_DRAFT_TOOL],
        tool_choice={"type": "tool", "name": "submit_draft"},
        messages=[{"role": "user", "content": user_message}],
    )
    usage = ClaudeUsage(
        input_tokens=message.usage.input_tokens, output_tokens=message.usage.output_tokens
    )

    tool_use_block = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        raise DraftSchemaError("Claude did not call the submit_draft tool", usage=usage)

    try:
        draft = DraftOutput.model_validate(tool_use_block.input)
    except ValidationError as e:
        raise DraftSchemaError(f"submit_draft input failed validation: {e}", usage=usage) from e

    if context_chunks and any(
        i < 0 or i >= len(context_chunks) for i in draft.cited_chunk_indices
    ):
        raise DraftSchemaError(
            "cited_chunk_indices referenced a chunk outside the provided context", usage=usage
        )

    return draft, usage
