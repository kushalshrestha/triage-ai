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
