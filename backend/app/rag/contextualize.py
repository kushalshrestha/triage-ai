from dataclasses import dataclass
from typing import Literal

from anthropic import Anthropic

from app.agent.ollama_client import generate_raw
from app.config import get_settings

PROMPT_VERSION = "v1"

ContextualizationProvider = Literal["claude", "ollama", "heuristic"]

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

# Ollama's /api/generate is a flat-completion interface (no cache_control,
# no separate document/chunk message parts like the Claude call below) —
# same instructions, folded into one prompt string.
_OLLAMA_CONTEXT_PROMPT = """You are given a full document and one chunk extracted from it.

Document:
{doc_content}

Chunk:
{chunk_content}

Give a short, succinct context (1-2 sentences) that situates this chunk \
within the overall document, for the purpose of improving search \
retrieval of the chunk. Respond with ONLY the context, nothing else.

Context:"""


@dataclass
class ClaudeUsage:
    input_tokens: int
    output_tokens: int


def generate_chunk_context(
    document_content: str,
    chunk_content: str,
    *,
    provider: ContextualizationProvider,
    title: str,
    chunk_index: int,
    total_chunks: int,
) -> tuple[str, ClaudeUsage | None]:
    """Situate one chunk within its parent document, via whichever
    provider is chosen (see ADR-0015 for the measured comparison behind
    that choice — `"ollama"` is the default, not `"claude"`).
    `usage` is only ever populated for `"claude"`, since Ollama and the
    heuristic have no per-token API cost to report.
    """
    if provider == "claude":
        return _generate_chunk_context_claude(document_content, chunk_content)
    if provider == "ollama":
        return _generate_chunk_context_ollama(document_content, chunk_content), None
    return _generate_chunk_context_heuristic(title, chunk_index, total_chunks), None


def _generate_chunk_context_claude(
    document_content: str, chunk_content: str
) -> tuple[str, ClaudeUsage]:
    """Ask Claude to situate one chunk within its parent document — the
    reference implementation of Anthropic's published technique. Not
    the default provider (see ADR-0015): measured no better than free
    Ollama, so kept as a faithful implementation of the named
    technique and as the baseline the comparison was measured against,
    not as the recommended path. The document block is cache_control'd
    so a document with N chunks pays full input-token cost once, not N
    times, when called once per chunk in a loop within the cache's TTL.
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


def _generate_chunk_context_ollama(document_content: str, chunk_content: str) -> str:
    """Ask the local Ollama model to situate one chunk within its parent
    document — free, and measured to tie doing nothing at all (ADR-0015),
    which makes it the default provider: the only one of the three that
    didn't measure worse than skipping contextualization entirely.
    """
    raw = generate_raw(
        _OLLAMA_CONTEXT_PROMPT.format(doc_content=document_content, chunk_content=chunk_content)
    )
    if "context:" in raw.lower():
        idx = raw.lower().rindex("context:")
        raw = raw[idx + len("context:") :]
    return raw.strip()


def _generate_chunk_context_heuristic(
    document_title: str, chunk_index: int, total_chunks: int
) -> str:
    """No model call at all — just the parent document's title and this
    chunk's position within it. Zero cost, zero latency, and measured
    (ADR-0015) to be the *worst* of the three options: near-identical
    boilerplate across every chunk of a document pulls their embeddings
    toward each other instead of distinguishing them.
    """
    return f"From the document \"{document_title}\" (part {chunk_index + 1} of {total_chunks})."
