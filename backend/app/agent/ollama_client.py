"""Shared low-level Ollama call, used by classify.py and judge.py.

`keep_alive: 0` forces Ollama to unload the model after every request
instead of keeping it warm. This was added after finding that a warm
model occasionally carried state across unrelated back-to-back calls —
sharing a long common prompt prefix (e.g. the same retrieved context
text in two different groundedness checks) sometimes produced a
response contaminated by the *other* call, even at temperature 0. It
reproduced with `OLLAMA_NUM_PARALLEL=1` too, so it wasn't purely a
concurrent-slot issue — something in Ollama's warm-model prompt/KV
caching. `keep_alive: 0` reliably eliminated it in testing at the cost
of real per-call latency (~5s reload vs. ~0.5s warm) — an acceptable
tradeoff for a guardrail whose whole job is correctness, not for
something latency-sensitive. See ADR-0009.
"""
import httpx

from app.config import get_settings
from app.tracing import tracer


def generate_raw(prompt: str) -> str:
    """Case-preserving variant of `generate()` — for callers where the
    response is stored/displayed as-is (e.g. contextual retrieval's
    chunk-context blurb, see ADR-0015) rather than pattern-matched
    against known lowercase keywords like `generate()`'s callers do.

    The one shared funnel every Ollama caller goes through — a single
    span here (ADR-0030) covers every Ollama call site for free.
    """
    settings = get_settings()
    with tracer.start_as_current_span("ollama_generate") as span:
        span.set_attribute("gen_ai.system", "ollama")
        span.set_attribute("gen_ai.request.model", settings.ollama_model_name)
        response = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_model_name,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0},
                "keep_alive": 0,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()
        # Already returned by Ollama, previously discarded — real
        # token counts, not estimated.
        if "prompt_eval_count" in body:
            span.set_attribute("gen_ai.usage.input_tokens", body["prompt_eval_count"])
        if "eval_count" in body:
            span.set_attribute("gen_ai.usage.output_tokens", body["eval_count"])
        return body["response"].strip()


def generate(prompt: str) -> str:
    return generate_raw(prompt).lower()
