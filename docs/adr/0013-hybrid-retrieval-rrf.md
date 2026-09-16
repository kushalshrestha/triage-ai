# ADR-0013: Hybrid retrieval (vector + keyword) via Reciprocal Rank Fusion

**Status:** Accepted
**Date:** 2026-09-16

## Context
Phase 9 (ADR-0012) built a real recall@k/MRR@k eval, but retrieval
itself (`retrieve_relevant_chunks`, `app/rag/retrieval.py`) was pure
cosine similarity over embeddings — no keyword/exact-match signal at
all. Pure embedding search has a known theoretical weak spot: it can
under-rank a chunk containing an exact term a user searched for (a
plan name, an error code, a specific phrase) if that token doesn't
carry much semantic weight to the embedding model. This phase adds a
second retrieval signal — Postgres's built-in full-text search — and
combines it with vector search via Reciprocal Rank Fusion (RRF).

Two things surfaced during this work that shaped the final design and
its honest conclusion:

1. **The existing golden set had zero headroom.** It already scored a
   perfect recall@3=1.0, MRR@3=1.0 on pure vector search (ADR-0012), so
   it couldn't demonstrate whether hybrid search helps at all. Three
   new, deliberately harder cases were added: two queries against an
   "Overage Error Code Reference" doc (exact alphanumeric codes,
   `ERR-7734`/`ERR-7735`, surrounded by generic billing-sounding prose
   similar to an existing doc), and two queries against a genuine
   minimal pair — "Storage Quota — Starter Plan" and "Storage Quota —
   Vantage Plan," identical wording except the plan name and the GB
   number.
2. **`app/agent/orchestrator.py:89-90` depends on the returned score
   meaning real cosine similarity.** It feeds `retrieved[0][1]`
   directly into `decide_outcome()`'s routing thresholds (`< 0.5`
   escalate, `0.5–0.8` draft, `≥ 0.8` auto-respond, per ADR-0008), and
   the same value is written to `agent_decisions.confidence_score` and
   `retrievals.similarity_score`, both `CHECK (0<=x<=1)` columns
   calibrated against cosine similarity. An RRF fusion score is a tiny
   number (max ≈ 1/61 + 1/61 ≈ 0.033 with k=60) — returning it as "the
   score" would silently collapse every routing decision to `escalate`
   regardless of actual retrieval quality.

## Decision
1. **Keyword side: Postgres native full-text search**, not a new
   library — `to_tsvector('english', content) @@ plainto_tsquery('english', query_text)`,
   ranked by `ts_rank`, backed by a new GIN index
   (`ix_doc_chunks_content_fts`, migration `2fe7f6fa8e01`). Consistent
   with ADR-0002's precedent of staying inside Postgres rather than
   standing up a new service or pulling in a BM25 library that would
   have to score every chunk in Python with no index support.
2. **Fusion: Reciprocal Rank Fusion, k=60** (the standard default from
   the original RRF paper). Each side contributes its top-10 candidates
   (`CANDIDATE_POOL`, wider than the final k=3 so fusion has real
   material to reorder); each candidate's fused score is
   `sum over rankers of 1/(60 + rank)`; the final top-k by that score
   is returned. Rank fusion sidesteps normalizing two very
   differently-shaped distributions (cosine similarity vs. `ts_rank`)
   onto a common scale.
3. **The returned score is always the chunk's real cosine similarity**
   — computed directly in Python from the query embedding and the
   chunk's stored embedding (plain dot-product/norm, no extra DB
   round-trip), never the RRF fusion score. RRF decides *which* chunks
   are selected and in *what order*; it does not change what the
   returned "confidence" number means to `orchestrator.py` or to the
   `CHECK (0<=x<=1)` columns. `retrieve_relevant_chunks()`'s signature
   and return type are unchanged — no caller needed to change.

## Honest result
Measured on the final 12-query golden set, using the same isolated
`db_session` test fixture for both implementations (an earlier
comparison run against the shared dev database was invalidated by
`ingest_document()`'s internal `db.commit()` polluting that database
with duplicate rows across runs — re-verified properly before drawing
any conclusion):

| Implementation | recall@3 | MRR@3 |
|---|---|---|
| Vector-only (Phase 9) | 1.00 | 1.00 |
| Hybrid (this phase) | 1.00 | 1.00 |

**Hybrid search does not show a measurable improvement over pure
vector search on this golden set** — including on the two new cases
built specifically to expose vector search's theoretical weak spot.
`sentence-transformers/all-MiniLM-L6-v2`, on a small (9-document),
clean, well-separated corpus, already ranks every query's correct
chunk at position 1 without any keyword help, exact codes and
near-duplicate minimal pairs included.

A further, more isolated stress test was run outside the golden set to
rule out the possibility that the golden set itself just wasn't
adversarial enough: 6 near-identical "generic productivity tip"
documents plus one topically unrelated document containing a single
made-up, meaningless token (`ZXQV-9182`), queried with that exact
token and nothing else — about as unfavorable a query as exists for an
embedding model (short, low-context, no real words). Both vector-only
and hybrid retrieved the correct document at rank 1, identically. Even
under a deliberately constructed worst case, this model still didn't
need the keyword signal.

This is being recorded honestly rather than reframed as a win: the RRF
fusion code path is implemented correctly and does engage (confirmed
it actually runs and returns results end-to-end), but every attempt to
construct a case where it would change the outcome, on this project's
data scale, failed to find one. This eval's corpus and this embedding
model are simply too capable/too clean, together, to have any headroom
left for hybrid fusion to demonstrate value. A larger, noisier, more
realistic knowledge base — with many genuinely similar documents
competing for the same query — is the condition under which hybrid
search is expected to actually pay off; this project doesn't have one
yet.

## Alternatives considered
- **Weighted linear blend of normalized scores** instead of RRF —
  requires normalizing cosine similarity and `ts_rank` onto a shared
  scale, fiddlier and less principled than rank fusion.
- **Recalibrating ADR-0008's routing thresholds to an RRF-scaled
  score** — rejected: bigger blast radius into agent orchestration (a
  different capability), no evidence current thresholds are wrong, and
  not what this phase is scoped to touch.
- **A Python BM25 library** (`rank-bm25` etc.) — no index, must score
  every chunk per query in-process; doesn't scale and duplicates what
  Postgres already provides for free.

## Consequences
- `retrieve_relevant_chunks()` now issues two queries per call instead
  of one (vector top-10, keyword top-10) plus in-Python RRF fusion —
  a real but small latency cost, not measured separately here since
  the eval doesn't track retrieval latency in isolation.
- The GIN index adds write-time cost to every `doc_chunks` insert
  (index maintenance) — not measured, expected to be negligible at
  this data volume.
- The golden set grew from 8 to 12 queries and from 6 to 9 seed docs;
  both new cases are kept permanently (not just as one-off validation)
  since they're legitimate regression guards — e.g. a future embedding
  model swap that *does* start confusing near-duplicate plan names
  would be caught by the Starter/Vantage pair even though today's
  model handles it fine.
- Recall/MRR thresholds (`RECALL_THRESHOLD=0.75`, `MRR_THRESHOLD=0.6`,
  unchanged from ADR-0012) still apply and remain comfortably
  conservative relative to the real measured 1.0/1.0.
- Revisit this eval's corpus size/realism before drawing any further
  conclusion about hybrid search's value — the honest finding here is
  "not proven on this test," not "doesn't work."
