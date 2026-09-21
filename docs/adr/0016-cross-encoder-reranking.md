# ADR-0016: Cross-encoder re-ranking

**Status:** Accepted
**Date:** 2026-09-20

## Context — the retrieval evolution, for anyone asking "why this and not that"
This is the fourth retrieval-architecture ADR in a row, and worth
reading as one continuous story rather than four isolated decisions:

1. **ADR-0007** (Phase 3): pure cosine similarity over embeddings —
   the baseline.
2. **ADR-0013** (Phase 10): added hybrid search (vector + Postgres
   full-text search, fused via Reciprocal Rank Fusion) — a general,
   well-established RAG technique, applied without first confirming it
   addressed a problem this project's data actually had. **Measured
   result: no proven benefit** over vector-only, on both the synthetic
   corpus and a deliberately adversarial isolated stress test.
3. **ADR-0015** (Phase 12): added contextual retrieval (an
   LLM-generated blurb prepended to a chunk before embedding, situating
   it within its parent document) — again a general technique, applied
   without first confirming this project had documents long/ambiguous
   enough to need it (it mostly doesn't — nearly the whole corpus is
   single-chunk). **Measured result: no proven benefit**; Claude and a
   free heuristic were both tried and measured, and Claude was
   deliberately dropped as the default (costs money, no better than
   free Ollama, which itself only tied doing nothing).
4. **This ADR** (Phase 13): cross-encoder re-ranking — different on
   purpose. ADR-0014 (Phase 11) diagnosed a *specific, real* failure on
   the real 89-doc FAQ corpus: a generic "return policy" query got
   crowded out of the top-3 entirely by three of the corpus's 17
   near-duplicate "Can I return a product if..." variants. This phase
   targets that diagnosed failure directly, rather than applying
   another general technique on spec.

**Why a cross-encoder is the right tool for that specific failure,
and why it doesn't have a scale problem.** The existing retrieval is a
*bi-encoder*: query and chunk are embedded separately, then compared
by cosine similarity — fast and indexable, which is what lets it scale
to millions of documents, but the model never sees query and chunk
together. A *cross-encoder* takes `(query, chunk)` as one joint input
and directly scores their relevance — meaningfully better at exactly
the "which of 17 near-identical documents actually answers this
specific query" disambiguation a bi-encoder alone tends to miss. The
tradeoff: a cross-encoder can't be pre-computed or indexed, so it's
only ever run over a small candidate set a fast first-stage retriever
already narrowed things down to — never the full corpus, regardless of
its size. This project's own `retrieve_relevant_chunks()` already caps
candidates at `CANDIDATE_POOL = 10` per side before RRF fusion, so a
reranker sitting on top of that never touches more than ~10 candidates
per query, at any corpus scale.

**Model: `cross-encoder/ms-marco-MiniLM-L6-v2`** (confirmed via direct
lookup, not memory) — Apache 2.0, ~90MB, the standard small/fast
choice for this task, trained on MS MARCO passage ranking. Zero new
dependencies: `CrossEncoder` ships inside `sentence-transformers`,
already a project dependency (ADR-0007). Outputs unbounded raw logits,
not a 0–1 score.

## Decision
1. **New module `app/rag/rerank.py`**: `rerank_candidates(query_text,
   candidates)` scores each `(query, chunk.content)` pair and returns
   the same `(chunk, cosine_similarity)` tuples, reordered by
   cross-encoder score. The cross-encoder's own logit is used only to
   decide order and is never returned as "the score" — this is the
   third time this exact invariant has mattered (ADR-0013, ADR-0015):
   `app/agent/orchestrator.py`'s routing thresholds and the
   `CHECK (0<=x<=1)` columns on `retrievals`/`agent_decisions` are
   calibrated against real cosine similarity, and a cross-encoder logit
   is neither bounded nor on that scale.
2. **`retrieve_relevant_chunks(..., use_reranking: bool = False)`** —
   opt-in, same pattern as `use_contextual_retrieval` (ADR-0015), so
   every prior ADR's documented baseline stays exactly reproducible.
   When `True`: RRF produces the top `CANDIDATE_POOL` (10, not just
   final k), the cross-encoder reorders that pool, then the final
   top-k is taken from the reranked order.
3. **Measured directly against the diagnosed failure**, not just an
   aggregate score — `test_retrieval_recall_and_mrr_on_real_corpus_with_reranking`
   explicitly checks the rank of the specific query ADR-0014 diagnosed
   as a miss, alongside the full 18-query recall@k/MRR@k, in its own
   isolated `db_session` (ADR-0013's lesson, reinforced again below).

## Real measured result

| Configuration | recall@3 | MRR@3 | Diagnosed-miss query rank |
|---|---|---|---|
| Without reranking (ADR-0014 baseline) | 0.944 (17/18) | 0.917 | not in top-3 (miss) |
| With reranking | 0.944 (17/18) | **0.852** | **3** (recovered) |

**The specifically diagnosed query partially recovered** — "What's
your policy if I want to send something back" went from missing the
top-3 entirely to rank 3, no longer crowded out by the near-duplicate
return-condition FAQs. That's the mechanism working exactly as
intended.

**But two other queries regressed, and the net MRR is worse, not
better.** Diagnosed directly (re-ingested the corpus once, ran both
configurations against the same clean copy, checked what was actually
returned — after first tripping over the now-familiar `ingest_document()`
internal-commit issue myself again and having to clean up a
duplicated corpus before trusting the diagnosis, see Consequences):

- **"My package says delivered but I never got it, what do I do"** —
  correctly ranked #1 without reranking ("What should I do if my
  package is lost or damaged?"). With reranking, that answer is
  **dropped from the top-3 entirely**, replaced by "Can I cancel my
  order?", an out-of-stock/pre-order FAQ, and a shipping-address FAQ —
  none of which answer the actual question. A clean, unambiguous
  regression from rank 1 to a complete miss.
- **"Can I send back an item that doesn't fit, I just don't want it
  anymore"** — correctly ranked #1 without reranking ("Can I return a
  product if I changed my mind?"). With reranking, that drops to rank
  2, edged out by "Can I return a product if I no longer have the
  original packaging?" — a plausible-sounding but wrong answer (the
  query is about not wanting the item, not about packaging).

Net: recall@3 stays at 17/18 either way (a different query fails), but
MRR@3 goes from 0.917 to 0.852 — **worse**, despite the mechanism
correctly doing what it was built to do for the one case it was
specifically aimed at. `cross-encoder/ms-marco-MiniLM-L6-v2` is
trained on general web-search passage ranking, not this project's
narrow e-commerce-FAQ domain, and in these two cases it confidently
preferred a less-relevant candidate over one the existing hybrid
search had already ranked correctly.

**Decision: `use_reranking` stays off by default.** A well-motivated,
correctly-implemented, evidence-targeted technique still nets out
negative here — recorded honestly rather than only reporting the part
that worked. This completes a real pattern across Phases 10, 12, and
13: three different, individually well-reasoned retrieval techniques,
all correctly implemented and rigorously measured, none showing a net
win on this project's actual data. That's not a failure of the
work — building the measurement infrastructure (ADR-0012) and using it
honestly, including on techniques the author expected to win and
didn't, is the actual deliverable of this phase of the project.

**Latency, measured**: the reranking eval ran in ~14s for a single
query's diagnostic check plus a full 18-query eval pass — no
prohibitive cost for ~10 candidates on CPU, unlike Ollama's per-call
reload latency (ADR-0015). Not the deciding factor here; quality was.

## Alternatives considered
- **A different, larger cross-encoder** — might reduce the two
  regressions above, at higher latency/memory cost. Not tried: the
  smallest standard model already nets negative, and there's no
  evidence a bigger model would fix these specific domain-mismatch
  errors rather than just being slower while making different ones.
  Worth revisiting only with a larger real golden set to actually
  measure it against.
- **Fine-tuning the cross-encoder on this project's own FAQ domain** —
  would likely fix the domain-mismatch problem directly, but is a
  meaningfully bigger lift (needs labeled training pairs at a scale
  this project's 18-query golden set doesn't provide) than this phase
  scoped in.
- **Making reranking default-on for query-time algorithm changes**
  (matching ADR-0013's precedent of hybrid search having no toggle at
  all) — rejected once the measured result came back negative; the
  opt-in default protects every prior ADR's documented baseline and
  matches ADR-0015's pattern for a technique that didn't prove out.

## Consequences
- No schema change — reranking is a pure query-time step.
- **A real process note, not just a technical one**: diagnosing the
  two regressions required re-learning a mistake already documented
  twice before (ADR-0013, and again in this session's own history) —
  `ingest_document()` commits internally regardless of the calling
  session, so a raw script against the real dev-database engine
  (rather than the isolated `db_session` test fixture) leaves data
  behind unless explicitly deleted, not just rolled back. Two
  consecutive ad-hoc diagnostic scripts each re-ingested the full
  89-doc corpus without cleaning up, producing a duplicated corpus
  that made the second diagnosis briefly look like a data bug before
  it was traced back to this. Cleaned up (confirmed back to the
  correct 4-document dev baseline) and re-diagnosed cleanly before
  reporting the numbers above.
- `rerank.py` and the `reranker_model_name` setting exist and are
  fully wired up, ready to flip on later if a larger/more realistic
  golden set or a domain-tuned model changes this result — the
  infrastructure investment isn't wasted even though the default
  stays off.
