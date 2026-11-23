# ADR-0032: PII redaction classifier — Presidio, enabled by default

**Status:** Accepted
**Date:** 2026-11-16

## Context
Last tracked item in `docs/capability-roadmap.md`, split out from
Phase 28's combined roadmap row. `app/guardrails/pii.py` was
pattern-based: email, phone, credit-card-shaped digit runs — nothing
else. Real, common PII in support tickets this regex **cannot catch
at all**: a customer's own name ("Hi, this is John Smith..."), a
street address/city, an SSN, an IP address — none have a fixed
syntactic shape a regex can match.

**Lesson carried forward from Phase 28 (ADR-0031), applied from the
start this time:** a classifier that looks perfect on an
adversarial/gap-focused test set can still fail on realistic content.
This phase's golden set included a `realistic_clean` category from
day one, not added reactively after a test failure.

## Decision
**Microsoft Presidio** (`presidio-analyzer` + `presidio-anonymizer`),
built on spaCy NER. The real, widely-used open-source PII
detection/anonymization framework — not a custom NER pipeline or a
paid API (AWS Comprehend PII, Azure PII detection) — free, local, no
new external account.

`redact_pii(text, use_classifier=True)` / `contains_pii(text,
use_classifier=True)` — **enabled by default**, pattern regex kept as
the deterministic floor for email/phone/credit-card, ORed with
Presidio for everything the regex structurally can't cover. Classifier
failure falls back to pattern-only, same philosophy as
ADR-0028/ADR-0031.

## Real measurement — three real findings, in order

**1. A genuine dependency conflict, found immediately, not assumed
away.** `presidio-analyzer`'s latest version (2.2.366) requires
`pydantic>=2.12.5`; this project pins `pydantic==2.9.2` project-wide.
Checked actual PyPI metadata across versions rather than guessing a
fix: `2.2.363`-`2.2.366` require the newer pydantic, `2.2.361`/`2.2.362`
require only `pydantic>=2.0.0,<3.0.0` — pinned to `2.2.362`, the newest
compatible version, rather than bumping a core, widely-used dependency
just for one guardrail feature.

**2. The model-size decision, reversed by real measurement.**
Presidio's own default NLP engine is `en_core_web_lg` (~400MB);
the plan going in was the smaller `en_core_web_sm` (~12MB, "right-sized"
like ADR-0007's embedding model). Real testing found `en_core_web_sm`
misclassified a brand name ("Shopify") as `LOCATION` at the *same*
confidence (0.85) as genuine location matches — no threshold could
separate them, the same lesson as ADR-0031. `en_core_web_lg` measured
zero false positives on the same cases. Switched model size based on
what was actually measured, not the original size-conscious plan.

**3. Even the larger model isn't perfect — measured honestly, not
hidden.** Expanding the `realistic_clean` category (10→18 examples,
specifically adding more brand-name-heavy tickets after the first
false positive) surfaced one more: "Slack" misclassified as `PERSON`.
Final real numbers:

| Category | Pattern-only | Classifier enabled (production default) |
|---|---|---|
| `regex_covered` | 100% | 100% |
| `ner_gap` | 0% (documented ceiling) | **100%** |
| `realistic_clean` | 100% | **94.4%** (17/18) |

## Decision on default: enabled, unlike ADR-0031's injection classifier
Same rigor, genuinely different conclusion — this is the point of
measuring rather than assuming a predetermined pattern:

- **Lower false-positive rate**: ~5.6% here vs. ~17% for the injection
  classifier.
- **Much milder consequence per false positive**: a PII false positive
  costs one redacted word in a ticket that still gets fully processed
  by the AI pipeline. An injection false positive causes an immediate,
  whole-ticket escalation that bypasses the pipeline entirely — a
  categorically bigger cost for roughly 3x the rate.
- **Higher stakes for the real benefit**: catching a name, SSN, or IP
  address before it reaches a third-party API (Claude) or a log line
  is a direct, tangible privacy/compliance improvement, not a
  defense-in-depth layer that's already backstopped elsewhere the way
  injection detection is (ADR-0026's `test_defense_in_depth_eval.py`).

`orchestrator.py` needed zero changes — it already calls
`redact_pii`/`contains_pii` with no override, so the new default takes
effect automatically.

## Alternatives considered
- **Try to fix the "Slack"-style false positives with a brand-name
  denylist** — rejected as whack-a-mole: there will always be another
  short, capitalized product name a generic NER model hasn't seen
  enough of. Documenting the real, measured, mild residual rate is
  more honest than chasing an incomplete fix.
- **`en_core_web_trf`** (spaCy's transformer-based model, typically
  more accurate still) — not evaluated this phase; a legitimate future
  comparison if the residual false-positive rate ever matters enough
  to revisit, using the same `test_pii_classifier_comparison_eval.py`
  mechanism.

## Consequences
- `backend/Dockerfile` bakes `en_core_web_lg` in at build time (spaCy
  models install as a pip package into site-packages, unlike the HF
  models already lazily cached via the `hf_cache` volume).
- This closes the last tracked item in `docs/capability-roadmap.md` —
  all 4 deferred enhancements from the original audit pass are now
  resolved (2 enabled/shipped as measured, 2 correctly implemented and
  kept opt-in/deferred based on real numbers).
- `docs/threat-model.md` item #2 updated: a real NER-based classifier
  now exists and is enabled, not just a named future option.
