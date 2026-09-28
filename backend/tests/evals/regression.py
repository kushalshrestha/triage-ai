"""Prompt regression-baseline snapshots (ADR-0024).

`docs/testing-strategy.md` layer 5 always named the right design —
"golden-set scores get snapshotted per prompt/model version" — but it
was never built; ADR-0010 deferred it as premature. It's been needed
three times since (ADR-0020, ADR-0022's three prompt-variant
experiments each), just never through this mechanism. A snapshot
*file*, not a live `eval_runs` query, because `record_eval_run`
(`tests/evals/conftest.py`) writes to the real app engine, and in CI
that's a fresh, ephemeral Postgres per workflow run — there is no
cross-run `eval_runs` history to compare against in CI at all. A
committed file is the only thing that actually persists across runs.
"""
import json
from pathlib import Path

BASELINE_PATH = Path(__file__).parent / "regression_baseline.json"

# Real measured cross-architecture score variance for an *unchanged*
# prompt was up to ~0.09 on a 12-example golden set (ADR-0020's CI
# incident, reconfirmed for classification) — a zero-tolerance
# comparison would false-positive on that noise alone. Chosen with
# that real number in hand, not guessed defensively in advance.
DEFAULT_TOLERANCE = 0.1


def load_baseline() -> list[dict]:
    with BASELINE_PATH.open() as f:
        return json.load(f)


def get_baseline_entry(run_type: str, model_used: str, metric: str | None = None) -> dict | None:
    for entry in load_baseline():
        if (
            entry["run_type"] == run_type
            and entry["model_used"] == model_used
            and entry.get("metric") == metric
        ):
            return entry
    return None


def check_regression(current_score: float, baseline_score: float, tolerance: float = DEFAULT_TOLERANCE) -> bool:
    """True if current_score is a real regression against baseline_score
    — i.e. lower by more than `tolerance`, not just noise-level lower.
    """
    return current_score < baseline_score - tolerance
