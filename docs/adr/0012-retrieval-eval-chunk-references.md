# ADR-0012: Retrieval golden-set chunk references and eval metrics

**Status:** Accepted
**Date:** 2026-09-15

## Context
ADR-0010's first-pass retrieval eval (`tests/evals/test_retrieval_eval.py`)
only checks **doc-level** recall — "did the correct document's title
show up anywhere in the top-k" — against a 5-example golden set where
every seed document is short enough to produce exactly one chunk. That
was enough to get a first number on the board, but it can't measure
*ranking quality* (rank 1 vs. barely-in-at-rank-3 look identical to
it), and Phase 10 (hybrid search) and Phase 11 (contextual retrieval)
both need a baseline that's actually sensitive to rank, not just
presence. This phase (9) upgrades the eval to chunk-level recall@k
plus MRR@k, which first requires deciding how a golden-set file
references "the correct chunk" at all — `DocChunk.id` is a
DB-generated UUID that's different every time a test re-seeds the
knowledge base, so it can't be hardcoded into a fixture file.

## Decision
1. **Reference expected chunks by `(doc_title, doc_source,
   chunk_index)`, not `DocChunk.id`.** Chunking is deterministic given
   fixed content (ADR-0007's fixed-size character windows), so
   `chunk_index` is stable across re-ingestion as long as the seed
   content string itself doesn't change. `doc_title` + `doc_source`
   together identify which seeded document a chunk belongs to — the
   eval fully controls its own seed set, so this pair is unique in
   practice even though the schema doesn't enforce it as a DB
   constraint (only `(knowledge_doc_id, chunk_index)` is unique-
   constrained, per ADR-0004).
2. **`retrieval_golden_set.jsonl` schema changes** from
   `{"query": ..., "expected_doc_title": ...}` to:
   ```json
   {"query": "...", "expected_chunks": [{"doc_title": "...", "doc_source": "eval-seed", "chunk_index": 0}]}
   ```
   `expected_chunks` is a list, not a single object, because a query
   can legitimately be satisfied by more than one chunk (e.g. two
   chunks of the same doc both mention the answer). Recall@k counts a
   hit if *any* listed chunk appears in the top-k; MRR uses the best
   (lowest) rank among them. `golden_set.jsonl` (the classification
   golden set) is untouched — this schema change is scoped entirely to
   the retrieval eval's own file.
3. **Metrics: recall@k and MRR@k, k=3** (matching the existing
   convention from ADR-0007/ADR-0010). MRR@k is the mean, across
   queries, of the reciprocal rank of the best-ranked expected chunk
   within the top-k (1/rank if found, 0 if not found within k).
   Recall@k alone can't tell "always rank 1" apart from "always
   barely scrapes into rank 3" — exactly the distinction Phase 10's
   hybrid-search comparison needs.
4. **A new multi-chunk seed document is required** for MRR to be a
   non-degenerate metric here: every existing seed doc is short enough
   to produce exactly one chunk, where recall@k and MRR@k are
   mathematically forced to agree (a hit is always rank 1). Added one
   ~1160-character doc ("Two-Factor Authentication & Device
   Management") that produces exactly two chunks under the existing
   800-char/100-overlap settings, with distinct-enough vocabulary per
   chunk (2FA setup vs. device revocation) that queries can be aimed
   at a specific, non-first chunk.
5. **Thresholds: recall@3 ≥ 0.75, MRR@3 ≥ 0.6**, over an 8-example
   golden set (up from 5). At N=8 each query is 12.5% of the score;
   0.75 tolerates up to 2 misses (slightly more lenient than the old
   0.8 doc-level threshold, since chunk-level matching is strictly
   harder). 0.6 MRR corresponds to a mean blend consistent with "most
   hits at rank 1, occasional rank 2" (1/1 = 1.0, 1/2 = 0.5, 1/3 =
   0.33). These are proposed conservatively ahead of running the eval,
   not fitted to the observed result — see the eval run logged in
   `eval_runs` (and pasted in the PR/commit) for the actual measured
   numbers this phase produced.

## Alternatives considered
- **Content-hash reference** (hash of the exact chunk text instead of
  `chunk_index`) — more robust to accidental chunk-boundary drift, but
  makes the golden-set file opaque and harder for a human to read or
  edit. Rejected: `chunk_index` is already stable under ADR-0007's
  deterministic chunking, and the golden set is meant to be
  human-authored/reviewed.
- **Keep doc-level matching, add a separate ranking metric computed
  over documents instead of chunks** — avoids the chunk-reference
  problem entirely, but throws away the exact information (which
  chunk, not just which doc) that Phase 10/11's comparisons need, and
  doesn't test anything new once a document has more than one chunk.
- **A single `expected_chunk` object instead of a list** — simpler,
  but forecloses the (real) case where more than one chunk of a
  document legitimately answers a query.

## Consequences
- `retrieval_golden_set.jsonl` is a breaking format change from the
  Phase 7 version; nothing else reads that file, so no migration is
  needed beyond rewriting it.
- Adding future seed documents to this golden set means knowing (or
  computing) their chunk boundaries ahead of time if the entry needs
  to target a specific non-zero chunk_index — a minor authoring cost,
  accepted as the tradeoff for a readable, DB-independent reference
  scheme.
- Both recall@k and MRR@k are logged as separate `EvalRun` rows
  (`run_type=RETRIEVAL`, distinguished by a `"metric"` key in the
  existing JSONB `details` column) — no schema change needed there.
