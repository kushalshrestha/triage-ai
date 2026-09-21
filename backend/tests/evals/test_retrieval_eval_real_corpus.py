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

# The specific query ADR-0014 diagnosed as a real, fully-explained miss:
# crowded out of the top-3 entirely by 3 of the corpus's 17 near-duplicate
# "Can I return a product if..." variants. Phase 13 (ADR-0016) exists
# specifically to see whether cross-encoder re-ranking recovers it.
DIAGNOSED_MISS_QUERY = "What's your policy if I want to send something back"


def _load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _seed_real_corpus(db: Session) -> list[dict]:
    faqs = _load_jsonl(FAQ_DATASET_PATH)
    for faq in faqs:
        ingest_document(db, title=faq["question"], source=SOURCE_LABEL, content=faq["answer"])
    return faqs


def _score(db: Session, use_reranking: bool) -> tuple[float, float, int, list[float]]:
    golden_set = _load_jsonl(GOLDEN_SET_PATH)
    hits = 0
    reciprocal_ranks = []
    for example in golden_set:
        results = retrieve_relevant_chunks(
            db, query_text=example["query"], k=K, use_reranking=use_reranking
        )
        rank = _rank_of_best_match(results, example["expected_chunks"])
        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1 / rank)
        else:
            reciprocal_ranks.append(0.0)
    recall = hits / len(golden_set)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    return recall, mrr, hits, reciprocal_ranks


def test_retrieval_recall_and_mrr_on_real_corpus(db_session: Session, record_eval_run):
    from app.config import get_settings
    from app.models import EvalRunType

    faqs = _seed_real_corpus(db_session)
    recall, mrr, hits, reciprocal_ranks = _score(db_session, use_reranking=False)
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
            "golden_set_size": len(_load_jsonl(GOLDEN_SET_PATH)),
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
            "golden_set_size": len(_load_jsonl(GOLDEN_SET_PATH)),
            "reciprocal_ranks": reciprocal_ranks,
        },
    )

    assert recall_passed, f"recall@{K} was {recall:.2f}, expected >= {RECALL_THRESHOLD}"
    assert mrr_passed, f"MRR@{K} was {mrr:.2f}, expected >= {MRR_THRESHOLD}"


def test_retrieval_recall_and_mrr_on_real_corpus_with_reranking(
    db_session: Session, record_eval_run
):
    """Phase 13 (ADR-0016): cross-encoder re-ranking measured against
    the same real corpus and golden set as the test above, in its own
    isolated db_session (ADR-0013's lesson — never compare variants
    inside one shared session/corpus). Includes a direct check on the
    specific query ADR-0014 diagnosed as a real miss, not just the
    aggregate score.
    """
    from app.config import get_settings
    from app.models import EvalRunType

    faqs = _seed_real_corpus(db_session)
    recall, mrr, hits, reciprocal_ranks = _score(db_session, use_reranking=True)
    recall_passed = recall >= RECALL_THRESHOLD
    mrr_passed = mrr >= MRR_THRESHOLD

    golden_set = _load_jsonl(GOLDEN_SET_PATH)
    diagnosed_example = next(ex for ex in golden_set if ex["query"] == DIAGNOSED_MISS_QUERY)
    diagnosed_results = retrieve_relevant_chunks(
        db_session, query_text=DIAGNOSED_MISS_QUERY, k=K, use_reranking=True
    )
    diagnosed_rank = _rank_of_best_match(diagnosed_results, diagnosed_example["expected_chunks"])
    print(f"\nDiagnosed-miss query rank with reranking: {diagnosed_rank}")

    model_used = (
        f"hybrid(local/{get_settings().embedding_model_name}+postgres-fts)"
        f"+rerank({get_settings().reranker_model_name})"
    )
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
            "diagnosed_miss_rank": diagnosed_rank,
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
            "diagnosed_miss_rank": diagnosed_rank,
        },
    )

    assert recall_passed, f"recall@{K} was {recall:.2f}, expected >= {RECALL_THRESHOLD}"
    assert mrr_passed, f"MRR@{K} was {mrr:.2f}, expected >= {MRR_THRESHOLD}"
