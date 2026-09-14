"""RAG retrieval-quality eval — the "extend golden set with
retrieval-quality examples" item from project-brief.md's build
sequence. Threshold over a fixed dataset, per testing-strategy.md's
eval layer, even though the embedding model here is local/fast rather
than a hosted call (see ADR-0007).

k=3 and the 0.8 recall threshold are starting points, not tuned yet —
this eval is exactly the mechanism for tuning them with real numbers
later, per ADR-0007.
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.rag.ingestion import ingest_document
from app.rag.retrieval import retrieve_relevant_chunks

GOLDEN_SET_PATH = Path(__file__).parent / "retrieval_golden_set.jsonl"
RECALL_THRESHOLD = 0.8
K = 3

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
}


def _load_golden_set() -> list[dict]:
    with GOLDEN_SET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def test_retrieval_recall_at_k_meets_threshold(db_session: Session, record_eval_run):
    from app.config import get_settings
    from app.models import EvalRunType

    for title, content in SEED_KNOWLEDGE_BASE.items():
        ingest_document(db_session, title=title, source="eval-seed", content=content)

    golden_set = _load_golden_set()
    hits = 0
    for example in golden_set:
        results = retrieve_relevant_chunks(db_session, query_text=example["query"], k=K)
        retrieved_titles = {chunk.knowledge_doc.title for chunk, _score in results}
        if example["expected_doc_title"] in retrieved_titles:
            hits += 1

    recall = hits / len(golden_set)
    passed = recall >= RECALL_THRESHOLD

    record_eval_run(
        run_type=EvalRunType.RETRIEVAL,
        model_used=f"local/{get_settings().embedding_model_name}",
        score=recall,
        threshold=RECALL_THRESHOLD,
        passed=passed,
        details={"k": K, "golden_set_size": len(golden_set), "hits": hits},
    )

    assert passed, f"recall@{K} was {recall:.2f}, expected >= {RECALL_THRESHOLD}"
