"""LLM-as-judge groundedness check via Ollama (see ADR-0009) — a
second, independent check on whether Claude's draft is actually
supported by the retrieved context, or makes unsupported claims.
"""
from app.agent.ollama_client import generate

PROMPT_VERSION = "v1"

_PROMPT_TEMPLATE = """Context: {context}

Reply: {reply}

Question: Does the reply only use information present in the context above, \
without adding any new facts? Answer yes or no.

Answer:"""


def assess_groundedness(reply_text: str, context_chunks: list[str]) -> tuple[bool, str]:
    context = "\n\n---\n\n".join(context_chunks) if context_chunks else "(no context provided)"
    raw = generate(_PROMPT_TEMPLATE.format(context=context, reply=reply_text))
    return _parse_verdict(raw), raw


def _parse_verdict(raw: str) -> bool:
    if "answer:" in raw:
        raw = raw.rsplit("answer:", 1)[1]

    words = raw.strip().strip(".").split()
    if not words:
        return False  # fail-safe: empty response treated as not grounded
    return words[0] == "yes"
