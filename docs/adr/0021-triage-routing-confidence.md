# ADR-0021: Triage routing confidence + real routing-accuracy measurement

**Status:** Accepted
**Date:** 2026-09-22

## Context
Auditing "Triage agent" (project-brief.md: "retrieves similar tickets,
checks account/SLA via tool call, decides: auto-respond /
draft-for-review / escalate") against `app/agent/orchestrator.py`.
Two things that looked like gaps against the literal capability
description turned out to be deliberate, already-documented decisions,
not oversights:
- **"SLA"** — ADR-0008's Alternatives explicitly rejected a fabricated
  SLA/billing tool call: "there's no underlying data to back it; using
  real account data is more honest than inventing a subsystem."
- **"Retrieves similar tickets"** — served by the same knowledge-base
  retrieval mechanism; Knowledge Ingestion's own definition already
  folds "resolved tickets" into that same corpus, so a separate
  ticket-to-ticket similarity system isn't a missing piece.

Two real gaps were found, both traceable to future work ADR-0008
itself named and never followed up on:
1. **Routing confidence is computed before drafting, never
   reconciled with what actually got cited.** `top_similarity` (the
   top-*retrieved* chunk's similarity) drives `decide_outcome()` and
   is stored as `confidence_score` — before `generate_draft()` runs.
   Real evidence this matters (ADR-0019's Consequences): a live triage
   call had the top-retrieved chunk at 0.83 similarity, but Claude
   cited the rank-2 chunk at 0.79 instead.
2. **`test_triage_eval.py`'s threshold coverage was never grown.**
   ADR-0008 named it as "the mechanism for revisiting [the 0.5/0.8
   thresholds] with real accuracy numbers" — never done. It's also
   `@pytest.mark.costly` on 3 examples, checking escalate-vs-not only,
   never actually exercising the `auto_respond`/`draft_for_review`
   split.

**On "modern trends," explicitly considered and deliberately not
adopted**: a more "agentic" redesign would let the LLM itself reason
about routing confidence. ADR-0008 already rejected a second Ollama
call for confidence scoring as unreliable for a small local model, and
Phase 17 (ADR-0020) just measured a real, reproduced capability
ceiling in this same model family on a comparably nuanced judgment
task — 0.636 accuracy, three prompt rewrites didn't fix it. Adding
more LLM-decided routing logic now would cut directly against that
fresh evidence. The correct move is the opposite of "more agentic":
keep routing deterministic and numeric (ADR-0008's original choice),
and make the deterministic signal *more accurate* by tying it to
actual generation provenance — the same "grounding-aware confidence"
idea behind Phase 16's citation-scoping (ADR-0019), applied one step
further down the pipeline.

## Decision

### 1. Post-draft citation-confidence check
New pure function `citation_meets_confidence_bar(decision_type,
min_cited_similarity)` in `orchestrator.py` — same "pure, testable
without model/DB" pattern as `decide_outcome()`. After drafting,
`min_cited_similarity` (the *weakest* of the cited chunks — a reply is
only as trustworthy as its weakest citation) is checked against the
threshold implied by the current `decision_type` (the auto-respond
threshold if `AUTO_RESPOND`, the draft threshold otherwise). If it
fails and `decision_type == AUTO_RESPOND`, downgrade to
`DRAFT_FOR_REVIEW` — same downgrade pattern as the existing
groundedness check. Logged as a new `GuardrailCheckType.CITATION_CONFIDENCE`
row (migration `77ace4240509`, `ALTER TYPE ... ADD VALUE`, uppercase
label per ADR-0010's convention) and folded into `reasoning`.

Scope deliberately narrow: only the `AUTO_RESPOND`→`DRAFT_FOR_REVIEW`
step is implemented — the one with real evidence behind it. A further
`DRAFT_FOR_REVIEW`→`ESCALATE` cascade was considered and deferred,
not speculatively built ahead of evidence it's needed.

Tested via mocked `generate_draft`/`assess_groundedness`
(`test_agent_triage_api.py::test_citing_a_weaker_chunk_downgrades_auto_respond`)
— this logic is pure/deterministic, no real model call needed to prove
it: two docs ingested (one clearing the auto-respond threshold at the
top rank, one weaker), the mocked draft cites the weaker one, and the
decision correctly downgrades with the new guardrail check recorded.

### 2. A real, free, larger triage routing-accuracy eval
New `tests/evals/triage_routing_golden_set.jsonl` — 15 examples (5 per
bucket), built against the **real MakTek corpus** already vendored
from Phase 11, not a new synthetic one. Every example's expected
bucket was verified against real retrieval before being committed to
the golden set, not just assumed — several initial candidates
(`"Creating an account"`, `"Cancel my order"`, a bulk-discount
question) landed in an unexpected bucket once the ticket *subject*
was included in the query text (the real production query is
`subject\nbody`, not body alone), and were adjusted based on what was
actually measured, the same discipline used to build every other
golden set in this project.

New `tests/evals/test_triage_routing_eval.py` — free (`decide_outcome`
only depends on retrieval similarity, computed before Claude is ever
called, so no Claude call is needed to test routing itself), runs in
`eval-smoke` (blocking every PR). **Real measured result: 15/15
(1.0)** against the current 0.5/0.8 thresholds — no threshold change
warranted; the existing guesses hold up against a real, diverse
25-times-larger sample than the 3 examples the costly eval had.
`ACCURACY_THRESHOLD = 0.8` gives headroom below the measured 1.0.

The existing costly `test_triage_eval.py` (3 examples, real Claude)
is unchanged — its job narrows to confirming the full pipeline
(including the groundedness and citation-confidence downgrades) works
end-to-end with real models; broad threshold coverage is now the new
free eval's job.

## Alternatives considered
- **A `DRAFT_FOR_REVIEW`→`ESCALATE` citation-confidence cascade** —
  symmetric with the `AUTO_RESPOND` case, but no real evidence yet
  motivates it; deferred rather than speculatively built.
- **An LLM-decided routing/confidence step** — rejected; see the
  "modern trends" reasoning above. Directly contradicted by this
  project's own fresh measurement (ADR-0020) of this exact model
  family's reliability ceiling on a similar judgment task.
- **Growing `test_triage_eval.py` in place** instead of a new file —
  rejected: that file is inherently costly (real Claude), so growing
  its example count 5x would meaningfully increase CI spend for
  coverage that doesn't actually require a Claude call to validate.

## Consequences
- Migration `77ace4240509` adds one enum value; no other schema change.
- `confidence_score` on `AgentDecision` still reflects pre-draft
  `top_similarity`, unchanged in meaning — the new check is a
  *separate*, later signal, not a redefinition of an existing one.
- The 0.5/0.8 thresholds are now backed by a real, verified 15-example
  measurement instead of the original "starting guess" framing in
  ADR-0008 — still worth revisiting again if this golden set grows
  further or real production volume ever accumulates.
