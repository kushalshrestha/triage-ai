# ADR-0031: Injection detection classifier — implemented, measured, kept opt-in

**Status:** Accepted
**Date:** 2026-11-16

## Context
Last of the 4 deferred enhancements. `app/guardrails/injection.py` is
deliberately simple keyword/substring matching. ADR-0026 already
measured the real gap: `direct` (exact phrases) 100% caught, `evasion`
(trivial paraphrases) **0% caught** — a keyword list can't generalize
to rewording.

## Decision
A real, pre-trained prompt-injection text classifier
(`protectai/deberta-v3-base-prompt-injection-v2`, HuggingFace) run
locally via `transformers` — already a dependency (Phase 13's
cross-encoder reranker), no new package. Chosen over a paid detection
API (Lakera Guard, Azure AI Content Safety Prompt Shields) to stay
local/free/no-new-account, and over a custom-trained classifier since
a real, widely-used model for exactly this task already exists (also
used by the LLM Guard open-source guardrails library).

`is_likely_injection(text, use_classifier=False)` — pattern list ORed
with the classifier when enabled, short-circuiting (classifier never
called) when the pattern already matched. Classifier failures (model
load error, inference exception) fall back to pattern-only rather than
crashing, same philosophy as ADR-0028.

## Real measurement — a genuine surprise, then a real problem
First pass, against the existing `safety_golden_set.jsonl`
(ADR-0026's 4 categories) with the classifier enabled, threshold 0.97
(picked from real score separation — see below): **100% across every
category**, including `semantic_hijack` (3/3) — a category with *zero*
injection-style phrasing, which a prompt-injection classifier had no
obvious reason to catch. Genuinely unexpected; recorded honestly as a
real result on this golden set, not evidence semantic-hijack detection
is solved in general.

**The golden set's blind spot, caught by testing against realistic
ticket content instead of just adversarial examples:** every existing
category (including `false_positive`) is adversarial-flavored — none
of them represent an ordinary, non-adversarial support ticket.
Re-running the integration suite surfaced real failures on
completely benign test fixtures ("forgot my password", "email me when
it's reset"), which led to building a **new `realistic_benign`
category** (12 examples — ordinary password/billing/shipping/feature
tickets) specifically to measure this. Real result:

| Category | Pattern-only (production) | Classifier enabled |
|---|---|---|
| `direct` | 100% | 100% |
| `evasion` | 0% | **100%** |
| `false_positive` | 100% | 100% |
| `semantic_hijack` | 0% | **100%** |
| `realistic_benign` | 100% | **83%** (10/12) |

**Root cause of the `realistic_benign` misses, diagnosed not just
observed:** both false positives ask the system to "send/email X to
me" — "email me at jane.doe@example.com when it's reset", "resend
[the confirmation] to me." Real injection/exfiltration attacks commonly
take exactly this shape ("send the data to this address"), and the
classifier appears to have learned that pattern broadly enough to
flag it even in completely ordinary contexts. Checked whether a higher
confidence threshold could filter these out without losing real
catches: it can't — the false positives score 0.987-1.000, the same
range as genuine attacks (0.980-1.000) and even some correctly-passed
`realistic_benign` examples (up to 1.000 confidence *in the SAFE
label*) — there's no score-based separation available, this is a
genuine precision ceiling of the model on this input distribution, not
a threshold-tuning problem.

## Decision on default: kept opt-in, off by default
A ~17% false-positive rate on ordinary tickets (2/12, likely higher
with more realistic data given the small sample) is a real production
cost: this guardrail's only action is immediate escalation (zero model
calls), so every false positive means a completely routine ticket skips
the entire AI pipeline for no reason. Weighed against closing the
`evasion`/`semantic_hijack` gaps, this doesn't net out favorably as a
default without further tuning or a different model — so it isn't
enabled by default. This is the same treatment this project has
already given three other real, correctly-implemented techniques that
didn't prove net-beneficial on real data: hybrid search (ADR-0013),
contextual retrieval (ADR-0015), cross-encoder re-ranking (ADR-0016) —
all kept, all measured, all off by default, not deleted.
`orchestrator.py` needed **zero changes** — it already calls
`is_likely_injection(raw_text)` with no override, so production
behavior is completely unaffected by this phase.

## Alternatives considered
- **Raise the classifier threshold further to suppress false
  positives** — rejected, measured not assumed: no threshold separates
  the `realistic_benign` false positives from genuine attacks; a
  higher bar would also start missing real injections.
- **Try a different/larger injection-detection model** — a legitimate
  next step if this capability is ever prioritized further, not done
  here: this project's "measure, don't assume" discipline cuts both
  ways — chasing a better model without a specific candidate and real
  comparison data would be guessing, not measuring.
- **Only enable the classifier on tickets the pattern list already
  finds suspicious** — rejected: by definition those are already
  caught by the pattern list; this would add latency/model cost to the
  cases that need it least.

## Consequences
- Golden set grows from 14 to 26 examples, closing the "far smaller
  than every other golden set" gap this category had — now comparable
  in size to the others (11-18).
- New `tests/evals/test_injection_classifier_comparison_eval.py`
  documents the opt-in path's real numbers permanently — if a better
  model or tuning approach is tried later, this is the mechanism to
  re-measure against, mirroring ADR-0022/ADR-0029's provider-comparison
  pattern.
- `docs/threat-model.md` item #1 updated: a real classifier now exists
  as a measured, available (not default) upgrade path, not just a
  named future option.
- This closes the last of the 4 deferred enhancements tracked in
  `docs/capability-roadmap.md`. The PII redaction classifier upgrade
  (Presidio) remains untouched — a separate, later phase if pursued.
