from collections.abc import Callable, Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory() -> Callable[[], Session]:
    """A dependency wrapping `SessionLocal`, for code that needs to open
    its own session outside the request-scoped `Depends(get_db)` cycle —
    a `BackgroundTasks` callback, which runs after the request's own
    session has closed (see ADR-0017). A real FastAPI dependency (not a
    hardcoded import of `SessionLocal`) so tests can override it, the
    same way `get_db` is overridden, instead of silently opening a
    connection to the real dev database from inside a test.
    """
    return SessionLocal
