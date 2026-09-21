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
1. **New module `app/rag/contextualize.py`**: `_generate_chunk_context_claude()`,
   using Anthropic's own published prompt template (confirmed directly
   from their current documentation, not approximated) and prompt
   caching (`cache_control: {"type": "ephemeral"}`) on the document
   content block, so a document with N chunks pays full input-token
   cost once, not N times.
2. **A second implementation, `_generate_chunk_context_ollama()`,
   added after review** — the first version of this ADR defaulted to
   Claude without seriously weighing it against ADR-0008's own routing
   rule ("routine, cheap work → local Ollama; complex generation →
   Claude"). A short blurb situating a chunk is arguably closer to
   routine summarization than complex grounded generation, so this was
   worth actually measuring, not just asserting either way. Required a
   small supporting refactor: `app/agent/ollama_client.py`'s shared
   `generate()` forces `.lower()` on every response (needed by
   `classify.py`/`judge.py`'s keyword matching, wrong for a stored,
   inspectable blurb) — extracted the raw call into `generate_raw()`,
   with `generate()` now a one-line wrapper (`generate_raw(prompt).lower()`).
   Zero behavior change for the two existing callers, confirmed by
   re-running the full unit+integration suite after the change.
3. **A third implementation, `_generate_chunk_context_heuristic()`** —
   after deciding not to use Claude at all, this checks whether a
   model call is even necessary: no LLM, just
   `f'From the document "{title}" (part {i+1} of {n}).'`, zero cost,
   zero latency. Measured, not assumed better for being simpler — and
   it measured *worst* of all three (see Real measured result).
4. **Consolidated behind one public dispatcher,
   `generate_chunk_context(..., provider=...)`** — the three
   implementations above are now private (`_`-prefixed); callers
   (just `ingest_document()`) go through the single generic entry
   point, which returns `(blurb, ClaudeUsage | None)` uniformly
   (`usage` is `None` for the two providers with no per-token cost to
   report) rather than each caller needing to know which provider
   returns what shape. `ContextualizationProvider` (the `Literal`
   type) now lives in `contextualize.py` too, imported by
   `ingestion.py` rather than redefined there.
5. **New nullable `doc_chunks.context_prefix` column** — the generated
   blurb, stored separately from `content`. `content` stays the pure
   original chunk text always (citations, KB UI display, search
   results); never silently polluted with meta-commentary.
6. **`ingest_document(..., use_contextual_retrieval: bool = False,
   contextualization_provider: Literal["claude","ollama","heuristic"] = "ollama")`**
   — contextualization only runs when the flag is `True` *and* the
   document produced more than one chunk (a single chunk has nothing
   to contextualize even if the caller opts in). Default behavior,
   every existing call site, is byte-for-byte unchanged — confirmed by
   re-running `test_retrieval_eval.py` and
   `test_retrieval_eval_real_corpus.py` after this change: identical
   passing results, same thresholds. `contextualization_provider`
   defaults to `"ollama"`, not `"claude"` — see Real measured result.
7. **One new long, multi-section document** ("Membership & Billing
   Policy," ~1,600 chars, 3 chunks) covering trial period,
   auto-renewal, cancellation, and refunds, with deliberate real
   ambiguity: multiple different "N days" windows (14-day trial, 7-day
   cancellation exception, 30-day refund eligibility) across different
   chunks, and one chunk (index 2) that starts mid-sentence ("...30
   days, and are not automatically triggered by cancellation...")
   without ever using the word "refund" prominently near its start.
8. **Four separate test functions**, not one comparing all variants
   inline — `test_without_contextual_retrieval`,
   `test_with_contextual_retrieval_ollama`, and
   `test_with_contextual_retrieval_heuristic` (all free — Ollama makes
   real local calls but no $ cost, so none of these are `costly` per
   that marker's specific "calls the real Claude API" definition), and
   `test_with_contextual_retrieval_claude` (`@pytest.mark.costly`,
   real Claude calls, runs in `eval-full` not `eval-smoke`). Each gets
   its own fully isolated `db_session`. This is a direct lesson from
   ADR-0013: comparing ingestion variants inside one shared
   session/corpus lets their chunks coexist and compete in ways that
   don't reflect any one configuration cleanly.
9. **Cost visibility via logging, not a tracking table** —
   `ingest_document()` logs total contextualization input/output
   tokens per document (Claude only — Ollama and the heuristic have no
   per-token API cost). `scripts/cost_report.py` reads
   `agent_decisions` (triage-scoped) and won't see this; building
   ingestion-cost tracking in is an explicit, open follow-up, not
   silently dropped.

## Real measured result
All four measured against the same 5-query golden set, each in its
own isolated `db_session` (confirmed empty except the one document
under test — no cross-document competition, unlike an early diagnostic
script run against the shared dev database that briefly appeared to
show a data bug and turned out to just be legitimate competition from
pre-existing unrelated FAQ docs there):

| Configuration | recall@3 | MRR@3 | wall-clock (ingestion + eval) |
|---|---|---|---|
| Without contextualization | 1.00 | 0.90 | 8.0s |
| With contextualization — Ollama (`llama3.2:1b`) | 1.00 | 0.90 | 36.7s |
| With contextualization — Claude | 1.00 | 0.87 | 9.7s |
| With contextualization — heuristic (title + position) | 1.00 | 0.80 | 7.9s |

**None of the three contextualization approaches improved retrieval
over doing nothing; the heuristic made it measurably worse.** All
diagnosed directly, not just measured:

- **Claude**: the query "Does cancelling my subscription automatically
  refund the last charge?" dropped from rank 2 (without) to rank 3
  (with). Chunk 1's Claude-generated blurb — "Cancellation **and
  refund** policies for subscriptions, including... eligibility
  requirements and timelines for refund requests" — legitimately
  mentions "refund" prominently, because chunk 1 genuinely straddles
  both the cancellation-exception and refund-policy topics. That made
  chunk 1 look *more* similar to refund-themed queries, pulling it
  ahead of the actual target chunk (index 2) rather than helping that
  chunk stand out.
- **Ollama**: the same query landed at rank 1 for chunk 1 and rank 2
  for chunk 2 — matching the "without" baseline's rank 2 for chunk 2
  exactly. Ollama's blurb for chunk 1 ("outlining the rules and
  procedures for canceling and refunding subscriptions") has the same
  topic-conflation property as Claude's, but the specific embedding
  shift wasn't quite enough to demote chunk 2 a further rank, unlike
  Claude's version. A real, measured difference in outcome from two
  different models describing the same ambiguous chunk boundary
  slightly differently — not a reason to prefer either on a 5-query
  sample.
- **Heuristic**: two of five queries dropped to rank 2 (the "forgot to
  cancel" and "does cancelling refund" queries — chunks 1 and 2). The
  blurb text (`From the document "Membership & Billing Policy" (part
  N of 3).`) is near-identical boilerplate across all three chunks of
  the same document — only the part number differs. Prepending shared
  boilerplate to every chunk of a document pulls their embeddings
  *toward each other* without adding any content that actually
  distinguishes one chunk's topic from its siblings', which is the
  opposite of what contextualization is supposed to do. Cheapest and
  fastest option; also the one that actively hurt.

**Latency is a clear, real difference between the two viable options
(Ollama and Claude).** Ollama's `keep_alive: 0` (ADR-0009 —
deliberately not kept warm, to avoid a documented cross-call
state-bleed bug) means every chunk pays a full model-reload cost;
three chunks pushed one test from ~9s (Claude, aided by prompt caching
across chunks) to ~37s. Free, but meaningfully slower — a real cost on
a synchronous, blocking ingestion request (the same operational
concern already flagged for large documents generally).

**Decision: don't use Claude for this.** Given no provider showed a
quality edge over doing nothing, Ollama is the one honest choice among
the three that don't cost real money and don't measure worse than the
baseline — heuristic is free and fast but actively harmful; Claude
costs money for a result no better than free Ollama. Default changed
to `contextualization_provider="ollama"`; Claude's implementation is
kept in the codebase as a working, tested reference (it's what
Anthropic's own published technique specifies), not as the
recommended path.

This is recorded honestly rather than reframed: all three
implementations are correct, all three mechanisms confirmed working
(real blurbs that measurably change ranking — just not in the
hoped-for direction for any of them here), on a document specifically
built to be favorable to the technique, on a 5-query sample too small
to treat any of these numbers as more than suggestive. All thresholds
(recall@3 ≥ 0.4, MRR@3 ≥ 0.3) are cleared by all four configurations
regardless.

## Alternatives considered
- **Contextualize every chunk regardless of document length** —
  rejected outright per the corpus-shape finding above; would spend
  real money/time contextualizing chunks with nothing to contextualize.
- **Store the contextualized text as `content` directly** instead of a
  separate `context_prefix` column — rejected: would leak
  meta-commentary about "this chunk's role in the document" into
  citations shown to users and into `submit_draft`'s grounding
  context, which is a correctness problem, not just a style one.
- **One test function comparing all variants** — rejected per the
  ADR-0013 lesson cited above.
- **Claude-only, no Ollama variant** — the initial version of this
  ADR; revisited after review pointed out it never weighed ADR-0008's
  own routing rule for this specific task.
- **Defaulting to the heuristic because it's cheapest** — the first
  draft of the Ollama-vs-Claude follow-up did exactly this, before
  actually measuring it. Measured instead of assumed, and it turned
  out to be the worst option, not the best — kept as a concrete
  example, in this ADR's own history, of why this project measures
  rather than guesses even when a choice looks obviously safe.

## Consequences
- `doc_chunks.context_prefix` is null for every existing row and for
  every future ingestion that doesn't opt in (the overwhelming
  majority, given the corpus-shape finding) — expected, not a data
  quality issue.
- Ingestion-time Claude cost is currently invisible to
  `scripts/cost_report.py` — a real, explicit gap, not a silent one.
  Ollama contextualization has no equivalent $ cost to track, only the
  latency shown above.
- `contextualization_provider` defaults to `"ollama"` — the one
  option, among the three measured, that costs nothing and didn't
  measure worse than not contextualizing at all. Not a strong
  endorsement of Ollama's blurbs specifically (it tied the do-nothing
  baseline, it didn't beat it) — more that Claude adds real cost for
  no measured benefit, and the heuristic actively hurt. Real latency
  cost remains (~4x slower than Claude for this one document);
  acceptable for now since this path triggers rarely by design
  (corpus-shape finding above). Revisit if a larger sample ever shows
  a clearer pattern for any of the three.
- Given the honest result here, enabling `use_contextual_retrieval` by
  default for any future long document is not yet justified by
  evidence from this project's own data, regardless of provider —
  revisit if a larger sample of genuinely long, multi-topic documents
  is ever added and shows a clearer pattern either way.
