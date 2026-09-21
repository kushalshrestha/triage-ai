from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db, get_session_factory
from app.main import app


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """A TestClient whose requests run against the transactional
    `db_session` fixture (backend/tests/conftest.py) instead of the
    real app engine, so each test's writes roll back automatically.

    `get_session_factory` is overridden the same way: without this, a
    `BackgroundTasks` callback (see app/routers/knowledge.py, ADR-0017)
    would call the real `SessionLocal`, bound to the real dev engine —
    not `db_session`'s test connection — silently writing to the actual
    dev database from inside a test (exactly the pollution bug ADR-0016
    hit and cleaned up manually). Returning `db_session` itself (not a
    new session on the same connection) matches `_override_get_db`
    below — this test setup already treats one shared session as "every
    request's session" for the whole test, so the background callback
    should join that, not open a second one.
    """

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_factory] = lambda: (lambda: db_session)
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_session_factory, None)
