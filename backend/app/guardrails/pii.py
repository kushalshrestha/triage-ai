"""Input guardrail: redacts likely PII from ticket text before it
reaches any model call or log line.

Hybrid as of Phase 29 (ADR-0032): the original pattern-based
email/phone/credit-card redaction is kept — a zero-latency,
deterministic floor — ORed with an opt-in Presidio-based NER
classifier that closes a real structural gap: the regex can never
catch a customer's own name, a street address/city, an SSN, or an IP
address, since none of those have a fixed syntactic shape the way an
email or phone number does.

`PII_ENTITY_TYPES` is a deliberately curated allowlist, not "redact
whatever Presidio finds" — real measurement showed Presidio's full
default entity set includes non-sensitive types (`DATE_TIME`, `URL`)
that would over-redact ordinary ticket text ("last week" is not PII).
Measured zero false positives on a realistic-clean golden set with
this curated list and no additional confidence threshold needed —
unlike ADR-0031's injection classifier, where no threshold could
separate real attacks from false positives, entity-type curation alone
did the job here.

The classifier call can fail (model load error, inference exception)
— falls back to pattern-only rather than crashing, same fail-safe
philosophy as ADR-0028/ADR-0031.

**Enabled by default** (`use_classifier=True`), unlike ADR-0031's
injection classifier. Real measurement found a much smaller
false-positive rate here (~5.6%, 1/18 on the realistic-clean golden
set — a brand name occasionally misclassified as PERSON/LOCATION) and,
critically, a much milder consequence per false positive: it costs one
redacted word in a ticket that still gets fully processed, not a
whole-ticket escalation bypassing the AI pipeline the way a false
positive in injection detection does. Given that and the real privacy
benefit of catching names/SSNs/addresses/IPs the regex structurally
can't, this nets out differently from the injection classifier even
though the method (real measurement before deciding) is identical —
see ADR-0032.
"""
import logging
import re
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]?){13,16}\b")

_PATTERNS = {
    "email": EMAIL_PATTERN,
    "credit_card": CREDIT_CARD_PATTERN,
    "phone": PHONE_PATTERN,
}

# en_core_web_lg, not the smaller en_core_web_sm originally planned —
# real measurement found en_core_web_sm misclassified a brand name
# ("Shopify") as a LOCATION entity at the same confidence (0.85) as
# genuine location matches, with no threshold able to separate them
# (same lesson as ADR-0031's injection classifier). en_core_web_lg
# measured zero false positives across the full golden set — see
# ADR-0032.
PII_MODEL_NAME = "en_core_web_lg"
PII_ENTITY_TYPES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "LOCATION",
    "IP_ADDRESS",
]


@lru_cache
def _get_analyzer() -> AnalyzerEngine:
    config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": PII_MODEL_NAME}],
    }
    provider = NlpEngineProvider(nlp_configuration=config)
    return AnalyzerEngine(nlp_engine=provider.create_engine())


@lru_cache
def _get_anonymizer() -> AnonymizerEngine:
    return AnonymizerEngine()


def _operators() -> dict[str, OperatorConfig]:
    return {
        entity: OperatorConfig("replace", {"new_value": f"[REDACTED_{entity}]"})
        for entity in PII_ENTITY_TYPES
    }


def _classifier_detects(text: str) -> bool:
    try:
        return bool(_get_analyzer().analyze(text=text, language="en", entities=PII_ENTITY_TYPES))
    except Exception:
        logger.exception("PII classifier call failed; falling back to pattern-only check")
        return False


def _classifier_redact(text: str) -> str:
    try:
        analyzer_results = _get_analyzer().analyze(text=text, language="en", entities=PII_ENTITY_TYPES)
        if not analyzer_results:
            return text
        return _get_anonymizer().anonymize(
            text=text, analyzer_results=analyzer_results, operators=_operators()
        ).text
    except Exception:
        logger.exception("PII classifier call failed; falling back to pattern-only redaction")
        return text


def contains_pii(text: str, use_classifier: bool = True) -> bool:
    pattern_match = any(pattern.search(text) for pattern in _PATTERNS.values())
    if pattern_match or not use_classifier:
        return pattern_match
    return _classifier_detects(text)


def redact_pii(text: str, use_classifier: bool = True) -> str:
    # Order matters: check the more specific credit-card pattern before
    # phone, since a 16-digit run would otherwise partially match phone.
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = CREDIT_CARD_PATTERN.sub("[REDACTED_CARD]", text)
    text = PHONE_PATTERN.sub("[REDACTED_PHONE]", text)
    if use_classifier:
        # Runs on the already-regex-redacted text — email/phone/card
        # are already gone by this point, so the classifier is really
        # only ever finding what the regex structurally can't: names,
        # addresses, SSNs, IPs.
        text = _classifier_redact(text)
    return text
