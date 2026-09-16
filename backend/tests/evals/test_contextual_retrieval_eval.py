"""Contextual retrieval eval — see ADR-0015. Every prior golden set
(synthetic, real-corpus) is almost entirely single-chunk documents,
where contextual retrieval has nothing to contribute (a single chunk
already contains 100% of its own context). This eval uses one
deliberately long, multi-section document instead, with real
cross-section ambiguity (multiple different "X days" windows — trial,
renewal, cancellation, refund — in different sections), so the
technique has real material to work on.

Two separate test functions, not one, so each gets its own fully
isolated `db_session` — comparing "with" and "without" inside a single
ingestion pass would put both versions' chunks in doc_chunks at once,
with retrieve_relevant_chunks() searching across both indistinguishably.
This mirrors a mistake made (and caught) in ADR-0013: a comparison
against a shared/reused session produced numbers that turned out to be
contamination artifacts.

Only `test_with_contextual_retrieval` calls Claude (contextualization
at ingestion time) and is marked costly; `test_without_contextual_retrieval`
makes no model calls and is free.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.rag.ingestion import ingest_document
from app.rag.retrieval import retrieve_relevant_chunks
from tests.evals.test_retrieval_eval import _rank_of_best_match

GOLDEN_SET_PATH = Path(__file__).parent / "contextual_retrieval_golden_set.jsonl"
DOC_TITLE = "Membership & Billing Policy"
DOC_SOURCE = "contextual-eval-seed"
RECALL_THRESHOLD = 0.4
MRR_THRESHOLD = 0.3
K = 3

LONG_DOC = (
    "Membership plans start with a 14-day free trial for new subscribers. During the trial, "
    "you have full access to every feature at no charge, and you can cancel at any time before "
    "the trial ends without being billed. If you do not cancel before the trial ends, your card "
    "on file is automatically charged for the plan you selected when you signed up. "
    "Subscriptions automatically renew at the end of each billing period, monthly or annually "
    "depending on the plan you chose. You will receive an email reminder three days before any "
    "renewal charge over 50 dollars. You can switch between monthly and annual billing at any "
    "time from Account Settings, and the change takes effect at your next renewal date, not "
    "immediately. You can cancel your subscription at any time from Account Settings, and "
    "cancellation always takes effect at the end of your current billing period, so you keep "
    "access until then. If you cancel within 7 days of a renewal charge specifically because "
    "you forgot to cancel before the trial or billing period rolled over, contact support and "
    "reference this policy so we can review the charge separately from a standard cancellation. "
    "Refund requests for any subscription charge must be submitted within 30 days of the "
    "original charge date to be eligible. Approved refunds are returned to the original payment "
    "method within 5-7 business days. Refunds are not available for charges older than 30 days, "
    "and are not automatically triggered by cancellation — cancelling stops future charges but "
    "does not itself refund a past one, so submit a separate refund request if you believe you "
    "were charged in error."
)


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _score(db: Session) -> tuple[float, float, int, list[float]]:
    golden_set = _load_golden_set()
    hits = 0
    reciprocal_ranks = []
    for example in golden_set:
        results = retrieve_relevant_chunks(db, query_text=example["query"], k=K)
        rank = _rank_of_best_match(results, example["expected_chunks"])
        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1 / rank)
        else:
            reciprocal_ranks.append(0.0)
    recall = hits / len(golden_set)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    return recall, mrr, hits, reciprocal_ranks


def test_without_contextual_retrieval(db_session: Session, record_eval_run):
    from app.config import get_settings
    from app.models import EvalRunType

    ingest_document(
        db_session, title=DOC_TITLE, source=DOC_SOURCE, content=LONG_DOC,
        use_contextual_retrieval=False,
    )
    recall, mrr, hits, rrs = _score(db_session)

    model_used = f"hybrid(local/{get_settings().embedding_model_name}+postgres-fts)"
    record_eval_run(
        run_type=EvalRunType.RETRIEVAL, model_used=model_used, score=recall,
        threshold=RECALL_THRESHOLD, passed=recall >= RECALL_THRESHOLD,
        details={"metric": "recall@k", "k": K, "corpus": "contextual-without", "hits": hits, "reciprocal_ranks": rrs},
    )
    record_eval_run(
        run_type=EvalRunType.RETRIEVAL, model_used=model_used, score=mrr,
        threshold=MRR_THRESHOLD, passed=mrr >= MRR_THRESHOLD,
        details={"metric": "mrr@k", "k": K, "corpus": "contextual-without", "reciprocal_ranks": rrs},
    )
    assert recall >= RECALL_THRESHOLD, f"recall@{K} was {recall:.2f}, expected >= {RECALL_THRESHOLD}"
    assert mrr >= MRR_THRESHOLD, f"MRR@{K} was {mrr:.2f}, expected >= {MRR_THRESHOLD}"


@pytest.mark.costly
def test_with_contextual_retrieval(db_session: Session, record_eval_run):
    from app.config import get_settings
    from app.models import EvalRunType

    ingest_document(
        db_session, title=DOC_TITLE, source=DOC_SOURCE, content=LONG_DOC,
        use_contextual_retrieval=True,
    )
    recall, mrr, hits, rrs = _score(db_session)

    model_used = f"hybrid(local/{get_settings().embedding_model_name}+postgres-fts)+claude-context"
    record_eval_run(
        run_type=EvalRunType.RETRIEVAL, model_used=model_used, score=recall,
        threshold=RECALL_THRESHOLD, passed=recall >= RECALL_THRESHOLD,
        details={"metric": "recall@k", "k": K, "corpus": "contextual-with", "hits": hits, "reciprocal_ranks": rrs},
    )
    record_eval_run(
        run_type=EvalRunType.RETRIEVAL, model_used=model_used, score=mrr,
        threshold=MRR_THRESHOLD, passed=mrr >= MRR_THRESHOLD,
        details={"metric": "mrr@k", "k": K, "corpus": "contextual-with", "reciprocal_ranks": rrs},
    )
    assert recall >= RECALL_THRESHOLD, f"recall@{K} was {recall:.2f}, expected >= {RECALL_THRESHOLD}"
    assert mrr >= MRR_THRESHOLD, f"MRR@{K} was {mrr:.2f}, expected >= {MRR_THRESHOLD}"
