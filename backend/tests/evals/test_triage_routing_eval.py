"""Real, free triage-routing-accuracy eval (ADR-0021) — the "revisit
[the 0.5/0.8 thresholds] with real accuracy numbers instead of
intuition" ADR-0008 named as future work, never done until now.

Routing (decide_outcome) only depends on retrieval similarity, computed
before Claude is ever called — so this seeds the real MakTek corpus
already vendored for Phase 11 (tests/evals/maktek_customer_support_faqs.jsonl)
and calls retrieve_relevant_chunks()/decide_outcome() directly, no
run_triage()/Claude needed. Free, so it can be meaningfully larger than
the existing costly tests/evals/test_triage_eval.py (3 examples,
escalate-vs-not only) — this one actually validates the auto_respond/
draft_for_review split, and stays in eval-smoke (blocking every PR).
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent.orchestrator import decide_outcome
from app.config import get_settings
from app.models import EvalRunType
from app.rag.ingestion import ingest_document
from app.rag.retrieval import retrieve_relevant_chunks

FAQ_DATASET_PATH = Path(__file__).parent / "maktek_customer_support_faqs.jsonl"
GOLDEN_SET_PATH = Path(__file__).parent / "triage_routing_golden_set.jsonl"
SOURCE_LABEL = "maktek-customer-support-faqs-v1"
ACCURACY_THRESHOLD = 0.8


def _load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def test_triage_routing_accuracy_on_real_corpus(db_session: Session, record_eval_run):
    faqs = _load_jsonl(FAQ_DATASET_PATH)
    for faq in faqs:
        ingest_document(db_session, title=faq["question"], source=SOURCE_LABEL, content=faq["answer"])

    golden_set = _load_jsonl(GOLDEN_SET_PATH)
    correct = 0
    details = []
    for example in golden_set:
        query = f"{example['subject']}\n{example['body']}"
        results = retrieve_relevant_chunks(db_session, query_text=query, k=3)
        top_similarity = results[0][1] if results else None
        actual = decide_outcome(top_similarity).value
        is_correct = actual == example["expected_decision"]
        correct += is_correct
        details.append(
            {
                "subject": example["subject"],
                "expected": example["expected_decision"],
                "actual": actual,
                "top_similarity": top_similarity,
                "correct": is_correct,
            }
        )

    accuracy = correct / len(golden_set)
    passed = accuracy >= ACCURACY_THRESHOLD

    record_eval_run(
        run_type=EvalRunType.ROUTING,
        model_used=f"local/{get_settings().embedding_model_name}",
        score=accuracy,
        threshold=ACCURACY_THRESHOLD,
        passed=passed,
        details={"corpus": SOURCE_LABEL, "corpus_size": len(faqs), "golden_set_size": len(golden_set), "examples": details},
    )

    assert passed, f"triage routing accuracy was {accuracy:.2f}, expected >= {ACCURACY_THRESHOLD}"
