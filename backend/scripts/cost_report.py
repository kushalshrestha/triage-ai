"""Cost/latency comparison report — the practical, buildable version of
project-brief.md's "Cost/latency comparison: Ollama-local vs. Claude-API
per task type" interview artifact. A report generator over real
agent_decisions columns (see ADR-0010), not a live dashboard.

Run: docker compose exec api python -m scripts.cost_report
(module invocation, not a bare script path — `app` needs to be on
sys.path, which only `-m` from the /app working directory guarantees)
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import engine
from app.models import AgentDecision


@dataclass
class ModelStats:
    model_used: str
    decision_count: int
    avg_confidence: float | None
    avg_latency_ms: float | None
    total_claude_input_tokens: int
    total_claude_output_tokens: int


def aggregate_by_model(rows: list[dict]) -> list[ModelStats]:
    """Pure aggregation logic, kept separate from the DB query so it's
    unit-testable without a database — groups agent_decisions-shaped
    dicts by model_used and computes summary stats.
    """
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["model_used"], []).append(row)

    stats = []
    for model_used, group in grouped.items():
        confidences = [r["confidence_score"] for r in group if r["confidence_score"] is not None]
        latencies = [r["total_latency_ms"] for r in group if r["total_latency_ms"] is not None]
        stats.append(
            ModelStats(
                model_used=model_used,
                decision_count=len(group),
                avg_confidence=sum(confidences) / len(confidences) if confidences else None,
                avg_latency_ms=sum(latencies) / len(latencies) if latencies else None,
                total_claude_input_tokens=sum(r["claude_input_tokens"] or 0 for r in group),
                total_claude_output_tokens=sum(r["claude_output_tokens"] or 0 for r in group),
            )
        )
    return sorted(stats, key=lambda s: s.model_used)


def fetch_agent_decision_rows() -> list[dict]:
    with Session(bind=engine) as session:
        rows = session.execute(
            select(
                AgentDecision.model_used,
                AgentDecision.confidence_score,
                AgentDecision.total_latency_ms,
                AgentDecision.claude_input_tokens,
                AgentDecision.claude_output_tokens,
            )
        ).all()
    return [
        {
            "model_used": r.model_used,
            "confidence_score": r.confidence_score,
            "total_latency_ms": r.total_latency_ms,
            "claude_input_tokens": r.claude_input_tokens,
            "claude_output_tokens": r.claude_output_tokens,
        }
        for r in rows
    ]


def print_report(stats: list[ModelStats]) -> None:
    if not stats:
        print("No agent_decisions rows yet — trigger some /tickets/{id}/triage calls first.")
        return

    header = (
        f"{'model_used':<45} {'count':>6} {'avg_conf':>9} {'avg_ms':>8} "
        f"{'claude_in':>10} {'claude_out':>10}"
    )
    print(header)
    print("-" * len(header))
    for s in stats:
        conf = f"{s.avg_confidence:.2f}" if s.avg_confidence is not None else "n/a"
        latency = f"{s.avg_latency_ms:.0f}" if s.avg_latency_ms is not None else "n/a"
        print(
            f"{s.model_used:<45} {s.decision_count:>6} {conf:>9} {latency:>8} "
            f"{s.total_claude_input_tokens:>10} {s.total_claude_output_tokens:>10}"
        )


if __name__ == "__main__":
    print_report(aggregate_by_model(fetch_agent_decision_rows()))
