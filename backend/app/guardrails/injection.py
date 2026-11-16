"""Input guardrail: flags likely prompt-injection attempts in ticket text.

Hybrid as of Phase 28 (ADR-0031): the original pattern list is kept —
it guarantees the `direct` golden-set category's 100% catch rate
deterministically, at near-zero latency, which a probabilistic
classifier alone can't promise — and ORed with a real, pre-trained
prompt-injection text classifier (`protectai/deberta-v3-base-prompt-injection-v2`)
that closes the pattern list's measured blind spot: trivial paraphrases
("please ignore all previous instructions" vs. the literal pattern
"ignore previous instructions") that a keyword list can't generalize
to. Same defense-in-depth philosophy already used throughout this
project (e.g. ADR-0021's retrieval-routing + groundedness pairing).

The classifier call can fail (model load error, inference exception)
— falls back to pattern-only rather than crashing the whole triage
request, same fail-safe-never-crash philosophy as ADR-0028.
"""
import logging
from functools import lru_cache

from transformers import Pipeline, pipeline as hf_pipeline

from app.config import get_settings

logger = logging.getLogger(__name__)

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore prior instructions",
    "disregard the above",
    "you are now",
    # Trailing colon required (ADR-0026): a bare "system prompt" false-
    # positives on innocent tickets mentioning a device's own prompt/UI
    # (e.g. "my thermostat's system prompt keeps asking for a PIN").
    "system prompt:",
    "act as if",
]


@lru_cache
def _get_classifier() -> Pipeline:
    settings = get_settings()
    return hf_pipeline("text-classification", model=settings.injection_classifier_model_name)


def _classifier_flags_it(text: str) -> bool:
    settings = get_settings()
    try:
        result = _get_classifier()(text)[0]
    except Exception:
        logger.exception("Injection classifier call failed; falling back to pattern-only check")
        return False
    return result["label"] == "INJECTION" and result["score"] >= settings.injection_classifier_threshold


def is_likely_injection(text: str, use_classifier: bool = False) -> bool:
    """`use_classifier` defaults to False — see ADR-0031. The classifier
    closes the pattern list's measured `evasion`/`semantic_hijack` gaps
    (0% -> 100% on the safety golden set) but was also measured to
    flag ~20% of ordinary, realistic support tickets as injection
    (anything shaped like "send/email X to me", a phrasing real
    injection/exfiltration attacks also commonly take) — a real
    precision/recall tradeoff that doesn't net out favorably for
    production traffic without further tuning or a different model.
    Kept available and measured, same as hybrid search/contextual
    retrieval/cross-encoder reranking (ADR-0013/0015/0016) — a real,
    correctly-implemented technique that isn't proven net-beneficial
    enough to enable by default yet.
    """
    lowered = text.lower()
    pattern_match = any(pattern in lowered for pattern in INJECTION_PATTERNS)
    if pattern_match or not use_classifier:
        return pattern_match
    return _classifier_flags_it(text)
