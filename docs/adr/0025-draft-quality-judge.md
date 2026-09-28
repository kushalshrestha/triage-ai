# ADR-0025: LLM-as-judge for draft quality

**Status:** Accepted
**Date:** 2026-09-28

## Context
project-brief.md's "Golden dataset + offline metrics" capability:
"50–100 labeled tickets; classification accuracy, RAG faithfulness,
LLM-as-judge for draft quality." Auditing what actually exists:
classification accuracy is covered (Phases 19-20), RAG faithfulness is
covered (groundedness eval, Phase 17) — but **"LLM-as-judge for draft
quality" didn't exist at all**. `app/agent/judge.py::assess_groundedness`
is the only judge in the system, and it's a binary grounded/not-
grounded check (ADR-0009) — nothing rated whether a draft is actually
*good*: helpful, appropriately toned, complete.
`docs/testing-strategy.md` has named the intended design since early
in this project and never built it: "LLM-as-judge quality >= 4/5" — a
1-5 scale.

Every golden set in this project is also smaller than
project-brief.md's "50-100 labeled tickets" target (11-18 examples
each). Between growing existing golden sets bigger and building the
missing quality-judge mechanism, the judge was the better-motivated
choice: it's a genuinely new, unmeasured dimension, not more of
something already covered, and it connects directly to Phases
17/19/20's findings — a **subjective, graded** rating task seemed
likely to be *harder* for the local 1B model than the binary
groundedness check that already showed a real reliability ceiling
(0.636 `reliable_accuracy`, ADR-0020).

**Deliberately scoped as an evals-layer addition, not a new production
guardrail.** Unlike `assess_groundedness` (wired into `orchestrator.py`,
affects real routing), this judge measures the pipeline's draft
quality offline over a golden set. Wiring it into live routing is a
separate, later decision if the numbers ever support it — the same
pattern as contextual retrieval and re-ranking (measured before ever
being considered for default-on).

## Decision

### `app/agent/quality.py` — a new judge, mirroring `judge.py`'s shape
`assess_draft_quality(reply_text, ticket_subject, ticket_body, context_chunks, provider="ollama") -> tuple[int | None, str]`
— a 1-5 rating, or `None` when the raw output doesn't parse (the same
honest-nullable pattern as `classify.py::_match_category`, ADR-0022,
rather than silently defaulting to some rating). `QualityJudgeProvider
= Literal["ollama", "claude"]`, mirroring `contextualize.py`/
`classify.py`'s established multi-provider dispatcher.

The Ollama prompt is short and direct — learning from ADR-0009 and
ADR-0020's repeated finding that elaborate instructions make this
specific model *worse*, not better — a one-line anchor per rating
(1 = doesn't address the question ... 5 = excellent), "respond with
ONLY the number," same `Context`/`Reply`/question shape as
`assess_groundedness`'s already-working prompt. The Claude judge uses
forced tool-use with an `enum`-constrained integer field, same
fairness rationale as ADR-0022's classification comparison.

### A real golden set spanning the full range
`tests/evals/draft_quality_golden_set.jsonl` — 12 examples, each
`{ticket_subject, ticket_body, context, reply, expected_rating}`,
deliberately varied rather than just "good vs. bad": an excellent
grounded reply (5), a correct-but-verbose/rambling one (3), a curt
reply missing key details (2), a fully non-responsive reply (1), an
accurate-but-dismissive tone (2), an honest graceful decline (5, see
Consequences), reusing this project's established FAQ content
(password reset, billing refund) for realism.

## Real measured result — the opposite of what was expected
`tests/evals/test_draft_quality_eval.py`, same "run it twice" structure
as ADR-0020 (`RUNS_PER_EXAMPLE = 2`), with `RATING_TOLERANCE = 1` (a
graded 1-5 judgment has legitimate subjective variance even between
careful human raters — an exact-match bar would be unreasonably strict
here, unlike groundedness's binary case):

| Metric | Score | Threshold |
|---|---|---|
| `consistency_rate` | **1.00** | >= 0.8 |
| `reliable_accuracy` (±1 tolerance) | **0.917** (11/12) | >= 0.75 |

**This directly contradicts the prior expectation.** A graded 1-5
quality judgment turned out to be *more* reliable for this local model
than the binary groundedness check (0.636). A plausible reason,
recorded honestly rather than left unexamined: quality judgments here
lean on strong, fairly surface-level stylistic signals (rambling text,
curt/rude phrasing, warm professional tone) that a small model can
likely pattern-match on directly — unlike groundedness, which requires
genuinely cross-referencing a specific claim against a specific
context passage, a deeper semantic task. Given this real result, **the
contingency for a Claude comparison ("if Ollama shows a real ceiling")
did not trigger** — Claude was not measured for this metric.

**The one miss was a defensible disagreement, not a clear model
error** — worth stating precisely rather than treating every miss as
equally a "model failure": a reply gracefully declining a feature
request ("we don't have dark mode, but I've noted your request...")
was rated 5 here for honesty and warmth, but the judge consistently
(2/2) rated it 3, plausibly because the reply doesn't fulfill the
customer's literal ask. Reasonable raters — human or model — could
differ on what "quality" means when the honest answer is "no."

## Alternatives considered
- **Zero-tolerance (exact match) scoring** — rejected: a 1-5 scale
  has real, legitimate subjective variance; treating any ±1 disagreement
  as a failure would understate a judge that's actually working
  reasonably well, the same reasoning ADR-0020 already applied to
  groundedness's tolerance-setting philosophy (there, for cross-run
  consistency rather than absolute scale, but the same principle).
- **Measuring Claude anyway, for completeness** — considered and
  skipped: the plan's own stated contingency for it wasn't met, and
  spending real Claude cost to confirm a result that's already
  measured as reliable isn't the disciplined use of "measure, don't
  assume" this project has followed elsewhere — that discipline cuts
  both ways, including not measuring more than the evidence calls for.
- **Wiring this into `orchestrator.py` immediately** — rejected as
  premature: this is an evals-layer metric per project-brief.md's own
  framing; whether to use it as a live guardrail (e.g. flagging a
  drafted reply for review below some quality bar) is a separate,
  later decision that should get its own measurement if it's ever
  proposed, not bundled into establishing the metric itself.

## Consequences
- No schema change, no production code touched — `app/agent/quality.py`
  is net-new, evals-only.
- Seeded into ADR-0024's regression-baseline mechanism
  (`tests/evals/regression_baseline.json`) immediately — this is
  exactly the pattern that mechanism exists to establish going
  forward: a new prompt's first real measurement becomes its
  committed v1 baseline right away, not retrofitted later.
- A real, usable "LLM-as-judge for draft quality" now exists, closing
  a capability gap named early in this project (`docs/testing-strategy.md`)
  and never built. It's currently local/free (Ollama) — a genuinely
  different cost story than the groundedness judge or classification's
  fallback routing needed, because the underlying task turned out to
  be easier for this model, not harder.
- Golden sets in this project remain smaller than project-brief.md's
  "50-100 labeled tickets" target — that gap is untouched by this
  phase and stays open, tracked in `docs/results.md`'s Known
  limitations.
