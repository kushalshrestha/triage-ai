"""RAG retrieval-quality eval — chunk-level recall@k and MRR@k against
a fixed golden set (see ADR-0012 for the golden-set schema and
threshold reasoning; ADR-0010 for why this is a `RETRIEVAL` eval_run).
Since Phase 10 (ADR-0013), `retrieve_relevant_chunks` is hybrid
(vector + Postgres full-text search, fused via RRF) rather than
pure cosine similarity — this eval exercises whichever implementation
is currently behind that function, without needing to change.

Threshold over a fixed dataset, per testing-strategy.md's eval layer,
even though the embedding model here is local/fast rather than a
hosted call (see ADR-0007).
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.rag.ingestion import ingest_document
from app.rag.retrieval import retrieve_relevant_chunks

GOLDEN_SET_PATH = Path(__file__).parent / "retrieval_golden_set.jsonl"
RECALL_THRESHOLD = 0.75
MRR_THRESHOLD = 0.6
K = 3

# See ADR-0012: the two-factor doc is the only seed doc long enough to
# produce more than one chunk (verified against the real chunk_text()
# output), which is what makes MRR a non-degenerate metric here.
SEED_KNOWLEDGE_BASE = {
    "Password Reset": (
        "To reset a forgotten password, click 'Forgot password' on the login "
        "screen and enter your account email. A reset link is sent that "
        "expires after one hour."
    ),
    "Billing Refunds": (
        "Refunds for subscription charges are processed within 5-7 business "
        "days back to the original payment method used at checkout."
    ),
    "Change Account Email": (
        "You can update the email address tied to your account from Account "
        "Settings > Profile > Email. A confirmation link is sent to the new "
        "address before the change takes effect."
    ),
    "Dark Mode Availability": (
        "Dark mode is currently available on the mobile app only. Dashboard "
        "dark mode support is on the roadmap but not yet released."
    ),
    "Data Export Status": (
        "Large account data exports can take up to 24 hours to complete. If "
        "an export appears stuck beyond that window, contact support with "
        "your export request ID."
    ),
    "Two-Factor Authentication & Device Management": (
        "Two-factor authentication adds a second verification step beyond "
        "your password. To enable it, go to Account Settings, then Security, "
        "then Two-Factor Authentication, and follow the prompts to link an "
        "authenticator app such as Google Authenticator or Authy. Once "
        "enabled, you will be asked for a six-digit code from the "
        "authenticator app every time you sign in from a device we do not "
        "already recognize. Backup codes are generated automatically the "
        "first time you turn on two-factor authentication, and each backup "
        "code can only be used once, so store the full list somewhere safe "
        "in case you ever lose access to your phone. Session and device "
        "management lives on a separate page under Account Settings, then "
        "Security, then Active Sessions. It lists every device currently "
        "signed into your account, its approximate location, and the last "
        "active timestamp. If you notice a device you do not recognize in "
        "that list, click Revoke to sign it out immediately, and we will "
        "require a fresh password entry the next time anyone tries to sign "
        "in from that device again. Reviewing this list periodically, "
        "especially right after you change your password, is a good habit."
    ),
    # Deliberately confusable with "Billing Refunds" above (both are
    # generic-sounding billing prose) except for two exact, unusual
    # tokens — added in Phase 10 (ADR-0013) specifically to give the
    # keyword side of hybrid search something pure vector search can't
    # already solve perfectly. See ai-architecture.md for the measured
    # before/after (vector-only vs. hybrid) on these two queries.
    "Overage Error Code Reference": (
        "When your account exceeds its plan included usage, the dashboard shows a billing "
        "notice with a reference code so support can identify exactly what triggered it. "
        "Reference code ERR-7734 means your account went over the API rate limit for the "
        "current billing cycle. Reference code ERR-7735 means your account went over its "
        "storage quota. Always include the exact reference code when you contact support so "
        "the right usage report can be pulled up immediately."
    ),
    # A true near-duplicate minimal pair — identical wording except the
    # plan name and the GB number — added alongside the error-code doc
    # to stress-test disambiguation between semantically-near-identical
    # documents. Measured result (ADR-0013): the local embedding model
    # already disambiguates both of these correctly at rank 1 without
    # any keyword help, same as the error-code case above.
    "Storage Quota — Starter Plan": (
        "The Starter plan includes 10 GB of storage. Once you reach the 10 GB limit, new "
        "uploads are blocked until you free up space or upgrade. You can check current usage "
        "anytime from the Storage page under Account Settings."
    ),
    "Storage Quota — Vantage Plan": (
        "The Vantage plan includes 500 GB of storage. Once you reach the 500 GB limit, new "
        "uploads are blocked until you free up space or upgrade. You can check current usage "
        "anytime from the Storage page under Account Settings."
    ),
}
SEED_SOURCE = "eval-seed"


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _rank_of_best_match(
    results: list, expected_chunks: list[dict]
) -> int | None:
    """1-indexed rank of the best (lowest-rank) expected chunk in results, else None."""
    expected_keys = {
        (c["doc_title"], c["doc_source"], c["chunk_index"]) for c in expected_chunks
    }
    for rank, (chunk, _score) in enumerate(results, start=1):
        key = (chunk.knowledge_doc.title, chunk.knowledge_doc.source, chunk.chunk_index)
        if key in expected_keys:
            return rank
    return None


def test_retrieval_recall_and_mrr_at_k_meet_thresholds(
    db_session: Session, record_eval_run
):
    from app.config import get_settings
    from app.models import EvalRunType

    for title, content in SEED_KNOWLEDGE_BASE.items():
        ingest_document(db_session, title=title, source=SEED_SOURCE, content=content)

    golden_set = _load_golden_set()
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
            "corpus": "synthetic",
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
            "corpus": "synthetic",
            "golden_set_size": len(golden_set),
            "reciprocal_ranks": reciprocal_ranks,
        },
    )

    assert recall_passed, f"recall@{K} was {recall:.2f}, expected >= {RECALL_THRESHOLD}"
    assert mrr_passed, f"MRR@{K} was {mrr:.2f}, expected >= {MRR_THRESHOLD}"
