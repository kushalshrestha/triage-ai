from dataclasses import dataclass

from anthropic import Anthropic

from app.config import get_settings

PROMPT_VERSION = "v1"

# Matches Anthropic's own published Contextual Retrieval prompt
# (see ADR-0015) rather than an approximation of it.
_DOCUMENT_CONTEXT_PROMPT = "<document>\n{doc_content}\n</document>"
_CHUNK_CONTEXT_PROMPT = (
    "Here is the chunk we want to situate within the whole document\n\n"
    "<chunk>\n{chunk_content}\n</chunk>\n\n"
    "Please give a short succinct context to situate this chunk within "
    "the overall document for the purposes of improving search retrieval "
    "of the chunk. Answer only with the succinct context and nothing else."
)


@dataclass
class ClaudeUsage:
    input_tokens: int
    output_tokens: int


def generate_chunk_context(document_content: str, chunk_content: str) -> tuple[str, ClaudeUsage]:
    """Ask Claude to situate one chunk within its parent document (see
    ADR-0015). The document block is cache_control'd so a document with
    N chunks pays full input-token cost once, not N times, when called
    once per chunk in a loop within the cache's TTL.
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    message = client.messages.create(
        model=settings.claude_model_name,
        max_tokens=200,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _DOCUMENT_CONTEXT_PROMPT.format(doc_content=document_content),
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": _CHUNK_CONTEXT_PROMPT.format(chunk_content=chunk_content),
                    },
                ],
            }
        ],
    )
    usage = ClaudeUsage(
        input_tokens=message.usage.input_tokens, output_tokens=message.usage.output_tokens
    )
    text_block = next((b for b in message.content if b.type == "text"), None)
    context = text_block.text.strip() if text_block is not None else ""
    return context, usage
