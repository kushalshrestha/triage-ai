"""LLM-as-judge groundedness check (see ADR-0009) — a second,
independent check on whether Claude's draft is actually supported by
the retrieved context, or makes unsupported claims.

`provider` added in Phase 26 (ADR-0029) — ADR-0020 measured a real
reliability ceiling on Ollama (`reliable_accuracy=0.636`); same
multi-provider pattern as `classify.py`/`quality.py` to measure whether
Claude does better, mirroring ADR-0022's classification comparison.
Production (`orchestrator.py`) keeps calling this with the default
`provider="ollama"` unless real numbers justify changing that.
"""
from typing import Literal

import httpx
from anthropic import Anthropic

from app.agent.ollama_client import generate
from app.config import get_settings

PROMPT_VERSION = "v1"

GroundednessProvider = Literal["ollama", "claude"]

_OLLAMA_PROMPT_TEMPLATE = """Context: {context}

Reply: {reply}

Question: Does the reply only use information present in the context above, \
without adding any new facts? Answer yes or no.

Answer:"""

_CLAUDE_SYSTEM_PROMPT = (
    "Determine whether a customer support reply is fully grounded in the "
    "provided context using the submit_groundedness_verdict tool. A reply "
    "is grounded only if it uses information present in the context, "
    "without adding any new facts."
)

_GROUNDEDNESS_TOOL = {
    "name": "submit_groundedness_verdict",
    "description": "Submit whether the reply is fully grounded in the provided context.",
    "input_schema": {
        "type": "object",
        "properties": {
            "grounded": {
                "type": "boolean",
                "description": (
                    "True if the reply uses only information present in the "
                    "context, without adding any new facts; false otherwise."
                ),
            }
        },
        "required": ["grounded"],
    },
}


def assess_groundedness(
    reply_text: str, context_chunks: list[str], provider: GroundednessProvider = "ollama"
) -> tuple[bool, str]:
    context = "\n\n---\n\n".join(context_chunks) if context_chunks else "(no context provided)"
    if provider == "claude":
        return _assess_groundedness_claude(reply_text, context)
    return _assess_groundedness_ollama(reply_text, context)


def _assess_groundedness_ollama(reply_text: str, context: str) -> tuple[bool, str]:
    try:
        raw = generate(_OLLAMA_PROMPT_TEMPLATE.format(context=context, reply=reply_text))
    except httpx.HTTPError as exc:
        # Same fail-safe philosophy as _parse_verdict's empty-response
        # handling below (see ADR-0028): if the judge itself is
        # unreachable, treat the reply as not grounded rather than
        # crashing the whole triage request — safer to downgrade
        # auto_respond than to risk an unverified reply going out.
        return False, f"groundedness check failed: {exc}"
    return _parse_verdict(raw), raw


def _parse_verdict(raw: str) -> bool:
    if "answer:" in raw:
        raw = raw.rsplit("answer:", 1)[1]

    words = raw.strip().strip(".").split()
    if not words:
        return False  # fail-safe: empty response treated as not grounded
    return words[0] == "yes"


def _assess_groundedness_claude(reply_text: str, context: str) -> tuple[bool, str]:
    # Forced tool-use with a boolean field — schema-guaranteed valid
    # output, same fairness rationale as ADR-0022's classification
    # comparison and quality.py's enum-constrained rating.
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.claude_model_name,
        max_tokens=50,
        system=_CLAUDE_SYSTEM_PROMPT,
        tools=[_GROUNDEDNESS_TOOL],
        tool_choice={"type": "tool", "name": "submit_groundedness_verdict"},
        messages=[{"role": "user", "content": f'Context: "{context}"\n\nReply: "{reply_text}"'}],
    )
    tool_use_block = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        # Same fail-safe default as the Ollama path: no verdict means
        # not grounded, never silently treated as passing.
        return False, "(no tool call)"
    grounded = tool_use_block.input.get("grounded")
    return bool(grounded), str(grounded)
