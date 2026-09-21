# ADR-0019: Citation-scoped groundedness verification

**Status:** Accepted
**Date:** 2026-09-21

## Context
This is project-brief.md's "Grounded retrieval" capability ("Draft
responses cite retrieved context, not model memory"). Auditing the
existing implementation (`app/agent/drafting.py`, `judge.py`,
`orchestrator.py`, the frontend) found the core mechanism already
reasonably modern: Claude is forced via tool-use
(`tool_choice: {"type": "tool", "name": "submit_draft"}`) to return
structured `cited_chunk_indices` instead of free-text citation
markers, and an out-of-range index is already rejected
(`generate_draft()`). But three real gaps, not polish:

1. **Citations weren't actually verified.** `assess_groundedness()`
   (ADR-0009) was called with *all* retrieved context
   (`context_texts`), not specifically the chunks Claude claims to
   have cited. A reply could cite chunk 0 while really drawing on
   chunk 2's content, and the "grounded ✓" badge would still pass — it
   only proved "grounded in *something* retrieved," not "grounded in
   what it says it used."
2. **No stable citation record.** `cited_chunk_indices` were positions
   in an in-memory list, never persisted against the `Retrieval` rows
   that already store `doc_chunk_id` per decision.
3. **Nothing surfaced to the reviewer.** The staff UI showed "N
   sources cited" as a bare count — not which chunk, not its text.

Also found: `ai-architecture.md`'s "Faithfulness" bullet under RAG
design was still the unfilled template placeholder despite ADR-0009
being implemented — fixed alongside this work.

## Decision

### 1. Require at least one citation whenever context was provided
`_DRAFT_TOOL`'s `cited_chunk_indices` schema gets `"minItems": 1` (a
steering hint). Real enforcement is in `generate_draft()`: if
`context_chunks` is non-empty and `draft.cited_chunk_indices` is
empty, raise `DraftSchemaError` — same "malformed output escalates
rather than surfacing a weak reply" philosophy as ADR-0009's schema
and out-of-range checks. `context_chunks` is always non-empty whenever
`generate_draft()` actually runs in production (drafting only starts
once `decide_outcome()` clears the draft threshold, which requires a
non-empty `retrieved` list), so a static schema constraint is
sufficient — no need to build it per-call.

### 2. Check groundedness against the cited chunks specifically
`orchestrator.py::run_triage` now builds
`cited_texts = [context_texts[i] for i in draft.cited_chunk_indices]`
and passes `cited_texts`, not `context_texts`, to
`assess_groundedness()`. Decision 1 guarantees this is non-empty
whenever a draft exists.

### 3. Persist which chunk was actually cited
New column `retrievals.cited: bool`, default `False`. Unlike
ADR-0017's `knowledge_docs.status` backfill, `False` is a *permanently*
correct default here — a pre-existing `Retrieval` row genuinely wasn't
marked cited, there's nothing to retroactively infer — so the
migration's `server_default` is kept, not dropped after backfill. Set
in the existing `Retrieval`-persisting loop:
`cited=(draft is not None and (rank - 1) in draft.cited_chunk_indices)`.
This relies on an implicit invariant — `rank` (1-based) is assigned by
enumerating the exact same `retrieved` list that `context_texts`
(0-based) was built from, in the same function call — flagged with a
comment at both call sites so a future refactor doesn't silently break
it.

### 4. Surface the actual cited source to the reviewer
`TicketEvent.payload` for `DRAFT_GENERATED` gets a new `citations`
field — `[{"knowledge_doc_title", "content"}]` for each cited chunk,
built from `retrieved` (already carries the joined-loaded
`knowledge_doc`, see `app/rag/retrieval.py`). The existing
`cited_chunk_indices` field is kept for raw-index debugging.
`TicketDetailPage.tsx` renders each citation's title + excerpt instead
of a bare count.

## Real measured evidence
Added to `tests/evals/test_groundedness_eval.py`, real Ollama calls:
- `REFUND_CHUNK` (refund timing) and `CANCELLATION_CHUNK`
  (subscription cancellation) are unrelated topics.
  `CANCELLATION_REPLY` is genuinely about cancellation.
- `assess_groundedness(CANCELLATION_REPLY, [REFUND_CHUNK, CANCELLATION_CHUNK])`
  → **passes** (today's pre-this-ADR behavior: the pool contains a
  supporting chunk, so whole-pool checking looks grounded regardless
  of which chunk was actually cited).
- `assess_groundedness(CANCELLATION_REPLY, [REFUND_CHUNK])` (simulating
  a misleading citation) → **fails**, correctly.

This is the concrete proof the tightening does something real: a
"right answer, wrong citation" case that whole-pool checking would
silently pass is caught once checking is scoped to what was actually
cited.

Also verified live against the running API (`POST /tickets/{id}/triage`
with a real Claude call): the retrieved pool's rank-1 chunk (highest
cosine similarity, 0.83) was a near-duplicate FAQ that turned out
**not** to be the one Claude actually cited — it cited the rank-2
chunk (0.79) instead, and `Retrieval.cited` correctly recorded that.
Confirms `cited` is a genuinely distinct, meaningful signal from
rank/similarity, not a redundant derivative of it.

## A testing gap found and closed along the way
`generate_draft()`'s own validation logic — including the *pre-existing*
out-of-range check — had **zero** direct test coverage before this:
every test exercising drafting mocks `orchestrator.generate_draft`
itself, bypassing its internals entirely. New `tests/unit/test_drafting.py`
mocks the `Anthropic` client at the boundary
(`app.agent.drafting.Anthropic`) to test both `DraftSchemaError` paths
and the happy path for real — closing a real, pre-existing gap, not
just covering new code.

## Alternatives considered
- **Trust the `minItems: 1` schema hint alone, skip the application-level
  check** — rejected: this project never trusts a model to perfectly
  honor a schema hint (see the existing out-of-range check, which
  exists for the same reason); an explicit check is the actual
  guarantee.
- **Check groundedness against both the cited chunks and the full pool,
  requiring both to pass** — rejected as unnecessary complexity: if the
  cited chunks alone don't support the reply, that's already
  sufficient to distrust the citation, regardless of what the rest of
  the pool contains.
- **Add a threat-model.md row** — considered, rejected: this tightens
  an existing internal verification mechanism, not a new external call
  or trust boundary (per CLAUDE.md's own trigger for that file).

## Consequences
- Migration `307a48b91d03` adds `retrievals.cited`; no other schema
  change.
- A reply that uses context but doesn't cite anything now escalates
  instead of drafting — a real, intentional behavior tightening, not
  just additive instrumentation.
- `docs/results.md` gets the two new eval numbers alongside the
  existing groundedness rows; `ai-architecture.md`'s placeholder
  "Faithfulness" bullet is replaced with the real mechanism.
