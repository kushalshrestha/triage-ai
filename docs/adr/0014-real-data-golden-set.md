# ADR-0014: Real-data golden set for retrieval eval

**Status:** Accepted
**Date:** 2026-09-16

## Context
Phase 9 (ADR-0012) and Phase 10 (ADR-0013) both hit the same wall: the
9-document synthetic corpus scored a perfect recall@3=1.0, MRR@3=1.0
on every attempt, including cases deliberately built to be hard (exact
alphanumeric codes, a hand-built near-duplicate minimal pair, an
isolated adversarial stress test). There was no headroom left to prove
whether any retrieval technique helps or hurts. This isn't a new
observation — `project-brief.md`'s review notes said, from the
project's earliest planning, "don't make this purely synthetic... look
for a public anonymized support-ticket dataset," and `docs/results.md`
has carried "Golden sets are synthetic... not done yet" as an open
limitation since Phase 8. This phase finally does it.

## Decision
1. **Dataset: MakTek `Customer_support_faqs_dataset`**
   (huggingface.co/datasets/MakTek/Customer_support_faqs_dataset).
   Apache 2.0, ungated, publicly downloadable, "open for use in
   personal and commercial projects" per the dataset card. Confirmed
   directly (not assumed): downloaded the real file, verified it's
   genuine JSONL (`{"question":..., "answer":...}`), 200 rows.
2. **Deduplicated before use — a real data-quality finding, not
   assumed clean.** The source file (named `train_expanded.json`
   upstream) turned out to repeat 10 specific questions 12-13 times
   each, consuming 121 of its 200 rows — 89 rows are genuinely unique.
   Ingesting the raw file would have created multiple `KnowledgeDoc`
   rows sharing an identical `(title, source, chunk_index)` key,
   breaking ADR-0012's assumption that tuple identifies exactly one
   chunk. Vendored the deduplicated 89-row set as
   `maktek_customer_support_faqs.jsonl`, not the raw 200-row file.
3. **Vendored as a static file, not fetched live in tests** — same
   hermetic-test reasoning as every other fixture in this project; a
   live HTTP dependency in a test/CI path is a flakiness risk this
   project doesn't take anywhere else.
4. **A separate eval file and golden set**, not merged into the
   existing synthetic one. `test_retrieval_eval.py` (9-doc corpus)
   stays exactly as it is — a fast, deterministic regression guard for
   specific structural cases that would be muddied by 89 more
   competing real documents. New:
   `test_retrieval_eval_real_corpus.py` + `real_corpus_golden_set.jsonl`,
   reusing `_rank_of_best_match` from the existing test file rather
   than duplicating it. Both evals log to `eval_runs` under the same
   `EvalRunType.RETRIEVAL`, distinguished by a `"corpus"` key in
   `details` (`"synthetic"` vs. `"maktek-customer-support-faqs-v1"`).
5. **18 hand-authored, paraphrased queries** against the 89-doc corpus
   (not copy-pasted from the source questions, so the eval measures
   retrieval rather than exact string matching), several deliberately
   targeting the corpus's genuine near-duplicate clusters (17 "Can I
   return a product if..." variants, 17 "Can I order a product if it
   is listed as..." variants, 12 "Can I request a product..."
   variants) — real ambiguity a synthetic corpus can't produce.

## Real measured result
Thresholds proposed conservatively ahead of running anything
(recall@3 ≥ 0.6, MRR@3 ≥ 0.4 — expecting a real, noisy 89-doc corpus
to be genuinely harder than the synthetic one). Actual measured result:

| Corpus | recall@3 | MRR@3 |
|---|---|---|
| Synthetic (9 docs, ADR-0013) | 1.00 | 1.00 |
| Real (89 docs, this phase) | **0.94** (17/18) | **0.92** |

This is exactly the headroom Phase 9/10 never had — genuine misses,
explainable ones:
- **The one recall miss**: query "What's your policy if I want to send
  something back" (paraphrasing the generic "What is your return
  policy?" FAQ) retrieved none of the correct chunk in the top-3.
  Diagnosed directly: the top-3 were all three *specific* "Can I
  return a product if it was [purchased as part of a bundle /
  damaged due to improper use / ...]" variants (scores 0.515/0.513/0.512
  — essentially tied), crowding out the generic policy FAQ entirely.
  17 near-duplicate specific-condition FAQs genuinely can outcompete
  one generic FAQ for a generic-sounding query — a real retrieval
  failure mode this project had never been able to observe before.
- **The one rank-2 case**: query about getting an out-of-stock item
  "reserved" landed the correct "request to be reserved" FAQ at rank
  2/3, edged out at rank 1 by a real but subtly different FAQ about
  ordering an item "available for backorder" (a different mechanism —
  automatic backorder fulfillment vs. a manual reservation request).
  Reasonable, explainable near-miss, not a bug.

Both thresholds cleared with real margin (0.94 ≥ 0.6, 0.92 ≥ 0.4) —
left unchanged rather than raised, consistent with keeping thresholds
as a conservative floor rather than pinned to the newest observed
value (same reasoning as ADR-0012/ADR-0013).

## Alternatives considered
- **Fetch the dataset live at test time** — rejected for the same
  hermetic-test reasons this project avoids network calls in
  non-`costly` evals everywhere else.
- **Merge the real corpus into the existing `test_retrieval_eval.py`**
  — rejected: would let 89 real documents compete with the synthetic
  corpus's hand-built structural test cases (e.g. a real "reset
  password" FAQ competing with the synthetic "Password Reset" doc for
  the same query), muddying what that eval is actually checking.
- **Keep the raw 200-row file, dedupe only in the ingestion loop** —
  rejected: the duplication is a property of the *source data*, not
  something ingestion should silently paper over; vendoring the
  cleaned file makes the actual corpus this eval runs against
  inspectable and correct at rest, not just correct after a runtime
  transform.

## Consequences
- The real-corpus eval adds ~9-10s to the eval-smoke run (measured
  directly: 89 documents ingested + embedded, 18 queries) — fast
  enough to stay in the blocking per-PR path alongside the other free
  evals, no `costly` marker needed.
- `docs/results.md`'s "Golden sets are synthetic" limitation is
  resolved for the *retrieval* eval specifically; `golden_set.jsonl`
  (classification) and the groundedness eval's two hand-crafted
  examples remain synthetic and are unaffected by this ADR.
- `project-brief.md`'s open decision "Public dataset (or synthetic
  strategy) for golden-set seeding" is resolved by this ADR for
  retrieval; classification/groundedness golden-set realism remains
  open if it's ever prioritized.
- Phase 12 (contextual retrieval, next on the roadmap) now has a real
  corpus with genuine headroom (0.94/0.92, not 1.0/1.0) to actually
  measure against — the problem Phase 10 couldn't solve.
