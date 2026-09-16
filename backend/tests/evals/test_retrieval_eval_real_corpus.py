"""Retrieval eval against a real, public dataset — see ADR-0014 for why
(Phase 9/10's synthetic 9-doc corpus scored a perfect 1.0/1.0 on every
attempt, including deliberately adversarial ones, leaving no headroom
to prove or disprove anything about retrieval quality).

Dataset: MakTek `Customer_support_faqs_dataset` (Hugging Face, Apache
2.0, https://huggingface.co/datasets/MakTek/Customer_support_faqs_dataset).
Vendored verbatim as `maktek_customer_support_faqs.jsonl`, deduplicated
from the source file's 200 rows down to 89 genuinely unique
question/answer pairs (the source file — named `train_expanded.json`
upstream — repeats several questions 12-13x each; ingesting those
duplicates as separate KnowledgeDoc rows would give several chunks the
exact same `(doc_title, doc_source, chunk_index)` key, which breaks
ADR-0012's assumption that tuple uniquely identifies one chunk).

This is a separate eval from `test_retrieval_eval.py` on purpose — that
one's small synthetic corpus is a fast, deterministic regression guard
for specific structural cases (multi-chunk boundaries, exact-code
lookup, a hand-built near-duplicate pair) and stays untouched; mixing
200 real FAQs into it would let real docs compete with the synthetic
ones for the same queries. This file measures retrieval quality at
realistic scale/noise instead.
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.rag.ingestion import ingest_document
from app.rag.retrieval import retrieve_relevant_chunks
from tests.evals.test_retrieval_eval import _rank_of_best_match

FAQ_DATASET_PATH = Path(__file__).parent / "maktek_customer_support_faqs.jsonl"
GOLDEN_SET_PATH = Path(__file__).parent / "real_corpus_golden_set.jsonl"
SOURCE_LABEL = "maktek-customer-support-faqs-v1"
RECALL_THRESHOLD = 0.6
MRR_THRESHOLD = 0.4
K = 3


def _load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def test_retrieval_recall_and_mrr_on_real_corpus(db_session: Session, record_eval_run):
    from app.config import get_settings
    from app.models import EvalRunType

    faqs = _load_jsonl(FAQ_DATASET_PATH)
    for faq in faqs:
        ingest_document(db_session, title=faq["question"], source=SOURCE_LABEL, content=faq["answer"])

    golden_set = _load_jsonl(GOLDEN_SET_PATH)
    hits = 0
    reciprocal_ranks = []
    for example in golden_set:
        results = retrieve_relevant_chunks(db_session, query_text=example["query"], k=K)
        rank = _rank_of_best_match(results, example["expected_chunks"])
        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1 / rank)
        else:
            reciprocal_ranks.append(0.0)

    recall = hits / len(golden_set)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    recall_passed = recall >= RECALL_THRESHOLD
    mrr_passed = mrr >= MRR_THRESHOLD

    model_used = f"hybrid(local/{get_settings().embedding_model_name}+postgres-fts)"
    record_eval_run(
        run_type=EvalRunType.RETRIEVAL,
        model_used=model_used,
        score=recall,
        threshold=RECALL_THRESHOLD,
        passed=recall_passed,
        details={
            "metric": "recall@k",
            "k": K,
            "corpus": SOURCE_LABEL,
            "corpus_size": len(faqs),
            "golden_set_size": len(golden_set),
            "hits": hits,
        },
    )
    record_eval_run(
        run_type=EvalRunType.RETRIEVAL,
        model_used=model_used,
        score=mrr,
        threshold=MRR_THRESHOLD,
        passed=mrr_passed,
        details={
            "metric": "mrr@k",
            "k": K,
            "corpus": SOURCE_LABEL,
            "corpus_size": len(faqs),
            "golden_set_size": len(golden_set),
            "reciprocal_ranks": reciprocal_ranks,
        },
    )

    assert recall_passed, f"recall@{K} was {recall:.2f}, expected >= {RECALL_THRESHOLD}"
    assert mrr_passed, f"MRR@{K} was {mrr:.2f}, expected >= {MRR_THRESHOLD}"
