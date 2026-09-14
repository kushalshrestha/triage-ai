import pytest

from scripts.cost_report import aggregate_by_model


def _row(model_used, confidence_score=None, total_latency_ms=None, claude_in=None, claude_out=None):
    return {
        "model_used": model_used,
        "confidence_score": confidence_score,
        "total_latency_ms": total_latency_ms,
        "claude_input_tokens": claude_in,
        "claude_output_tokens": claude_out,
    }


def test_empty_rows_returns_empty_stats():
    assert aggregate_by_model([]) == []


def test_groups_by_model_used():
    rows = [
        _row("ollama/llama3.2:1b", confidence_score=0.9),
        _row("ollama/llama3.2:1b,claude-haiku-4-5-20251001", confidence_score=0.6),
    ]
    stats = aggregate_by_model(rows)
    assert {s.model_used for s in stats} == {
        "ollama/llama3.2:1b",
        "ollama/llama3.2:1b,claude-haiku-4-5-20251001",
    }
    assert all(s.decision_count == 1 for s in stats)


def test_averages_confidence_and_latency_ignoring_nulls():
    rows = [
        _row("ollama/llama3.2:1b", confidence_score=0.8, total_latency_ms=100),
        _row("ollama/llama3.2:1b", confidence_score=0.4, total_latency_ms=200),
        _row("ollama/llama3.2:1b", confidence_score=None, total_latency_ms=None),
    ]
    [stats] = aggregate_by_model(rows)
    assert stats.decision_count == 3
    assert stats.avg_confidence == pytest.approx(0.6)
    assert stats.avg_latency_ms == pytest.approx(150)


def test_sums_claude_token_usage_treating_null_as_zero():
    rows = [
        _row("claude-haiku-4-5-20251001", claude_in=100, claude_out=40),
        _row("claude-haiku-4-5-20251001", claude_in=None, claude_out=None),
    ]
    [stats] = aggregate_by_model(rows)
    assert stats.total_claude_input_tokens == 100
    assert stats.total_claude_output_tokens == 40


def test_all_null_confidence_yields_none_average():
    rows = [_row("none", confidence_score=None)]
    [stats] = aggregate_by_model(rows)
    assert stats.avg_confidence is None


def test_results_sorted_by_model_used():
    rows = [_row("zeta"), _row("alpha")]
    stats = aggregate_by_model(rows)
    assert [s.model_used for s in stats] == ["alpha", "zeta"]
