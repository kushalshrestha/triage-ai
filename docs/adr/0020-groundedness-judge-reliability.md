# ADR-0020: Groundedness judge reliability study

**Status:** Accepted
**Date:** 2026-09-21

## Context
`project-brief.md`'s review notes and `ai-architecture.md`'s Open
Questions both flagged, since early in this project, that the
groundedness judge (`app/agent/judge.py::assess_groundedness`, a local
`llama3.2:1b` Ollama call at `temperature: 0`, ADR-0009) had only been
sanity-checked on 2 hand-crafted examples — not the "run it twice on
~10 examples, confirm stable scores" study needed before trusting it
for regression gating.

This stopped being hypothetical during Phase 16 (ADR-0019): a new eval
case failed in CI (x86_64 GitHub runner) while passing 5/5 locally
(arm64 dev machine) at `temperature: 0`. Investigating found two
distinct real problems:
1. **Cross-architecture nondeterminism.** A quantized small model's
   greedy decoding isn't guaranteed bit-identical across CPU
   architectures — different SIMD kernels can shift floating point
   results enough to flip a borderline verdict. Not a code bug;
   `temperature: 0` and `keep_alive: 0` (ADR-0009) were already in
   place.
2. **A worse, systematic weakness**, found trying to "fix" #1 with a
   starker example: checking a reply against a *completely unrelated*
   chunk made the judge say "grounded" 5/5 times, consistently — not
   flaky, wrong. The prompt ("does the reply only use information
   present in the context... without adding any new facts?")
   apparently doesn't reliably penalize irrelevance, only apparent
   contradiction.

Also worth naming: the old `test_groundedness_eval.py` hard-asserted
on individual hand-picked examples one at a time — the only eval file
in this project not following `testing-strategy.md` layer 3's own
convention ("assert against a threshold over a fixed dataset"). That's
very likely why one borderline example was a single point of CI
failure — every other eval aggregates across a golden set.

## Decision

### 1. A real golden set, aggregate-scored
New `tests/evals/groundedness_golden_set.jsonl` (11 examples, matching
the `retrieval_golden_set.jsonl` convention from ADR-0012), covering
5 "should be grounded" and 6 "should not be grounded" categories —
deliberately including both real failure modes just found
(`irrelevant_context`, `adjacent_wrong_topic`), not just easy cases.
`test_groundedness_eval.py` was rewritten into one test
(`test_groundedness_judge_reliability`, mirroring
`test_retrieval_eval_real_corpus.py`'s one-test-two-metrics shape):
for each example, call `assess_groundedness` twice (project-brief.md's
literal ask) and compute `consistency_rate` (both calls agree) and
`reliable_accuracy` (both calls agree **and** match the expected
label — disagreement always counts against this, never "half credit").

### 2. Real measured numbers for the current prompt (v1)
- **`consistency_rate = 1.0`** — perfect same-environment stability at
  temperature 0 across all 11 examples, 2 runs each. This confirms
  problem #1 above is specifically a *cross-architecture* issue; a
  single environment's repeated calls are perfectly stable. (This
  metric structurally can't detect cross-architecture drift — that
  needs a real run on different hardware, which is what actually
  happened in CI.)
- **`reliable_accuracy = 0.636`** (7/11) — a real, honestly-reported
  mediocre number. Breaking it down: v1 got all 5 "grounded" cases
  right, and 2 of 6 "not grounded" cases right (the blatant
  fabrication, and — this run — the adjacent-wrong-topic case). It
  missed `changed_specific_fact`, `partial_hallucination`,
  `irrelevant_context`, and `wrong_question_answered` — every case
  where the reply was topically plausible but the specific supporting
  detail was wrong, invented, or absent. **v1 has a strong bias toward
  "grounded"**: it only reliably flags a reply as ungrounded when it
  contains something wildly, obviously fabricated.

### 3. Three prompt rewrites tried, all measured worse — v1 kept, unchanged
Given problem #2 was a known, reproduced weakness, three revised
prompts were drafted and measured against the same golden set before
touching production code:

| Variant | Approach | `reliable_accuracy` |
|---|---|---|
| v1 (current) | Single question, "no new facts" | **0.636** |
| Candidate A | Longer, bulleted strictness criteria | 0.45 (flipped to near-total "yes" bias — worse than v1 on everything, including the case v1 got right) |
| Candidate B | Short, reframed around "supported by" + "differs from" | 0.45 (flipped to the *opposite* bias — near-total "no," failing every true-positive case) |
| Candidate C | v1's exact wording plus one added clause about topic relevance | 0.55 |

None beat v1. This echoes ADR-0009's own earlier finding that this
specific model responds unpredictably to prompt elaboration — longer,
more-explained prompts made it worse, not better, both times tried.
Three honest attempts, well-triangulated, converge on the same
conclusion: **this is a capability ceiling of a local 1B model on a
nuanced faithfulness-checking task, not a fixable prompt-wording bug.**
`PROMPT_VERSION` stays `"v1"`; `judge.py` is unchanged.

### 4. Thresholds set from what was actually measured
`CONSISTENCY_THRESHOLD = 0.8` (measured 1.0, headroom below).
`RELIABLE_ACCURACY_THRESHOLD = 0.5` (measured 0.636, enough headroom
that one example flipping — a known, documented, accepted risk from
problem #1 — doesn't fail CI outright, while still catching a real
regression, e.g. the judge call breaking entirely).

## Alternatives considered
- **Self-consistency / majority-vote at the production call site**
  (call `assess_groundedness` 3-5 times, take the majority) — a
  legitimate mitigation for LLM-judge noise, but doesn't fix problem #2
  (a *consistent* wrong answer votes the same way every time) and adds
  real latency (each Ollama call reloads the model, `keep_alive: 0`) to
  every triage decision that reaches drafting. Not adopted now; worth
  revisiting if a future incident shows same-environment inconsistency
  (this study found none) rather than the cross-architecture and
  capability-ceiling problems actually found.
- **A larger/different judge model** — would likely improve
  `reliable_accuracy` directly, at real cost/latency (this project's
  whole LLMOps story is routing routine work to a free local model,
  ADR-0010); worth a future measurement once there's a concrete
  candidate, not guessed at here.
- **Drop the judge entirely, rely only on citation-scoped checking
  (ADR-0019)** — rejected: the citation check verifies *which* chunks
  were used; the judge is the only check on whether the reply's actual
  wording is faithful to that chunk's content. Different failure modes,
  both still worth catching even if the judge is imperfect.

## Consequences
- `ai-architecture.md`'s "Judge reliability" line moves out of Open
  Questions into a real, resolved finding (per that section's own
  stated convention) — including the honest 0.636 number and the
  explicit "not fixed, ceiling identified" conclusion.
- No change to `app/agent/orchestrator.py` or `assess_groundedness()`'s
  signature — this was a measurement and prompt-experimentation
  exercise, not a call-site change.
- The mediocre `reliable_accuracy` is now a documented, known limit of
  the current groundedness guardrail — worth restating plainly in any
  future discussion of this project's guardrail coverage: it catches
  blatant fabrication reliably, and is weak on subtler
  wrong-but-plausible citations. ADR-0019's citation-scoping still adds
  real value independent of this ceiling (it's a different signal —
  *which* chunk was used — not *whether the wording matches it*).
