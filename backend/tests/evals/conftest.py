"""A session for recording EvalRun rows against the real dev database
(see ADR-0010) — not the ephemeral, rolled-back `db_session` fixture
from `tests/conftest.py`. That fixture's writes are deliberately never
persisted, which is right for test isolation but wrong for a
historical eval log: eval_runs rows are meant to survive past the test
process that wrote them.
"""
from collections.abc import Callable, Generator

import pytest
from sqlalchemy.orm import Session

from app.database import engine
from app.models import EvalRun
from tests.evals.regression import check_regression, get_baseline_entry


@pytest.fixture
def record_eval_run() -> Generator[Callable[..., EvalRun], None, None]:
    def _record(**kwargs) -> EvalRun:
        with Session(bind=engine) as session:
            run = EvalRun(**kwargs)
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    yield _record


@pytest.fixture
def assert_no_regression() -> Callable[..., None]:
    """See ADR-0024. Checks `score` against the committed
    `regression_baseline.json` entry for (run_type, model_used, metric)
    — not `eval_runs` history, which doesn't persist across CI runs.
    No entry yet means this is the first time this combination has
    been recorded; that's not a regression, just nothing to compare
    against yet.
    """

    def _check(run_type: str, model_used: str, score: float, metric: str | None = None) -> None:
        baseline = get_baseline_entry(run_type, model_used, metric)
        if baseline is None:
            return
        if check_regression(score, baseline["score"]):
            raise AssertionError(
                f"Regression detected for {run_type}/{model_used}"
                f"{f'/{metric}' if metric else ''}: score {score:.3f} is below the "
                f"committed baseline {baseline['score']:.3f} (prompt_version="
                f"{baseline['prompt_version']!r}) by more than the "
                f"tolerance. If this prompt/model change is intentional, update "
                f"tests/evals/regression_baseline.json deliberately, in this same "
                f"change, rather than silently accepting a worse score."
            )

    return _check
