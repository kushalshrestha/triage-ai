# ADR-0015: Contextual retrieval for multi-chunk documents

**Status:** Accepted
**Date:** 2026-09-16

## Context
Anthropic's published "Contextual Retrieval" technique: before
embedding a chunk, call Claude with the chunk *and its full parent
document*, asking for a short blurb situating that chunk within the
document; prepend the blurb to the chunk before embedding. It targets
context lost when a long document is split into many chunks.

Two things found during research, before writing any code:

1. **This project's corpus is almost entirely single-chunk.** Checked
   directly: every seed document across Phases 9-11 except one (the
   synthetic 2-chunk "Two-Factor Authentication & Device Management"
   doc) is single-chunk — including all 89 real FAQs from Phase 11. A
   single-chunk document already contains 100% of its own context;
   there's nothing to restore. Per direction, this phase implements
   the technique properly *and* adds a genuinely long, multi-section
   document so it has real material to work on, rather than shipping
   it unproven or skipping it.
2. **Contextualization must be opt-in, not automatic on chunk count.**
   The existing 2-chunk 2FA doc already lives in
   `test_retrieval_eval.py`, part of the free, blocking `eval-smoke`
   CI gate (ADR-0010). Automatic contextualization for any multi-chunk
   document would have silently turned that eval into one making real
   Claude calls on every PR, breaking CI's cost-boundedness guarantee.

## Decision
1. **New module `app/rag/contextualize.py`**: `generate_chunk_context()`,
   using Anthropic's own published prompt template (confirmed directly
   from their current documentation, not approximated) and prompt
   caching (`cache_control: {"type": "ephemeral"}`) on the document
   content block, so a document with N chunks pays full input-token
   cost once, not N times.
2. **New nullable `doc_chunks.context_prefix` column** — the generated
   blurb, stored separately from `content`. `content` stays the pure
   original chunk text always (citations, KB UI display, search
   results); never silently polluted with meta-commentary.
3. **`ingest_document(..., use_contextual_retrieval: bool = False)`**
   — contextualization only runs when the flag is `True` *and* the
   document produced more than one chunk (a single chunk has nothing
   to contextualize even if the caller opts in). Default behavior,
   every existing call site, is byte-for-byte unchanged — confirmed by
   re-running `test_retrieval_eval.py` and
   `test_retrieval_eval_real_corpus.py` after this change: identical
   passing results, same thresholds.
4. **One new long, multi-section document** ("Membership & Billing
   Policy," ~1,600 chars, 3 chunks) covering trial period,
   auto-renewal, cancellation, and refunds, with deliberate real
   ambiguity: multiple different "N days" windows (14-day trial, 7-day
   cancellation exception, 30-day refund eligibility) across different
   chunks, and one chunk (index 2) that starts mid-sentence ("...30
   days, and are not automatically triggered by cancellation...")
   without ever using the word "refund" prominently near its start.
5. **Two separate test functions**, not one comparing both inline —
   `test_without_contextual_retrieval` (free) and
   `test_with_contextual_retrieval` (`@pytest.mark.costly`, real
   Claude calls, runs in `eval-full` not `eval-smoke`). Each gets its
   own fully isolated `db_session`. This is a direct lesson from
   ADR-0013: comparing two ingestion variants inside one shared
   session/corpus lets both versions' chunks coexist and compete in
   ways that don't reflect either configuration cleanly.
6. **Cost visibility via logging, not a tracking table** —
   `ingest_document()` logs total contextualization input/output
   tokens per document. `scripts/cost_report.py` reads
   `agent_decisions` (triage-scoped) and won't see this; building
   ingestion-cost tracking in is an explicit, open follow-up, not
   silently dropped.

## Real measured result
Both measured against the same 5-query golden set, each in its own
isolated `db_session` (confirmed empty except the one document under
test — no cross-document competition, unlike an early diagnostic
script run against the shared dev database that briefly appeared to
show a data bug and turned out to just be legitimate competition from
pre-existing unrelated FAQ docs there):

| Configuration | recall@3 | MRR@3 |
|---|---|---|
| Without contextualization | 1.00 | 0.90 |
| With contextualization | 1.00 | 0.87 |

**Contextualization did not improve retrieval here — it made MRR
slightly worse**, and the reason is understood, not mysterious.
Without contextualization, the query "Does cancelling my subscription
automatically refund the last charge?" ranked the target chunk
(index 2, the refund-mechanics chunk) at rank 2. With contextualization,
it dropped to rank 3. Diagnosed directly by inspecting the generated
`context_prefix` values: chunk 1's blurb reads "Cancellation **and
refund** policies for subscriptions, including... eligibility
requirements and timelines for refund requests" — because chunk 1
genuinely straddles both the cancellation-exception and refund-policy
topics in the source document, its Claude-generated context legitimately
mentions "refund" prominently. That made chunk 1 look *more* similar to
refund-themed queries than before, pulling it ahead of chunk 2 rather
than helping chunk 2 stand out. Contextualizing a chunk that already
sits at a genuine topic boundary can increase its perceived relevance
to a neighboring chunk's topic, adding competition rather than removing
ambiguity.

This is recorded honestly rather than reframed: implemented correctly,
mechanism confirmed working (the blurbs are real, on-topic, and do
change ranking — just not in the hoped-for direction here), on a
document specifically built to be favorable to the technique, on a
5-query sample too small to treat either number as more than
suggestive. Both thresholds (recall@3 ≥ 0.4, MRR@3 ≥ 0.3) are cleared
by both configurations regardless.

## Alternatives considered
- **Contextualize every chunk regardless of document length** —
  rejected outright per the corpus-shape finding above; would spend
  real money contextualizing chunks with nothing to contextualize.
- **Store the contextualized text as `content` directly** instead of a
  separate `context_prefix` column — rejected: would leak
  meta-commentary about "this chunk's role in the document" into
  citations shown to users and into `submit_draft`'s grounding
  context, which is a correctness problem, not just a style one.
- **One test function comparing both variants** — rejected per the
  ADR-0013 lesson cited above.

## Consequences
- `doc_chunks.context_prefix` is null for every existing row and for
  every future ingestion that doesn't opt in (the overwhelming
  majority, given the corpus-shape finding) — expected, not a data
  quality issue.
- Ingestion-time Claude cost is currently invisible to
  `scripts/cost_report.py` — a real, explicit gap, not a silent one.
- Given the honest result here, enabling `use_contextual_retrieval` by
  default for any future long document is not yet justified by
  evidence from this project's own data — revisit if a larger sample
  of genuinely long, multi-topic documents is ever added and shows a
  clearer pattern either way.
