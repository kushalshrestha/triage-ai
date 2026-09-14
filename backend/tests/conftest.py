"""Shared DB fixtures for unit (model/constraint) and integration tests.

Tests run against a real Postgres database — a `<database>_test` sibling
of the dev DB on the same `docker compose` `db` service — created and
torn down here, not against a mocked engine, because pgvector and enum
constraints only mean something when checked by the real database.
"""
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Base


def _urls() -> tuple[sa.engine.URL, str]:
    """Return (maintenance URL pointing at the admin DB, test DB name)."""
    url = sa.make_url(get_settings().database_url)
    test_db_name = f"{url.database}_test"
    return url.set(database="postgres"), test_db_name


def _recreate_test_database() -> sa.engine.URL:
    maintenance_url, test_db_name = _urls()
    admin_engine = sa.create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": test_db_name},
        )
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db_name}"'))
        connection.execute(sa.text(f'CREATE DATABASE "{test_db_name}"'))
    admin_engine.dispose()
    return maintenance_url.set(database=test_db_name)


@pytest.fixture(scope="session")
def test_engine() -> Generator[sa.Engine, None, None]:
    test_url = _recreate_test_database()

    engine = sa.create_engine(test_url)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()

    maintenance_url, test_db_name = _urls()
    admin_engine = sa.create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db_name}"'))
    admin_engine.dispose()


@pytest.fixture
def db_session(test_engine: sa.Engine) -> Generator[Session, None, None]:
    """A session whose writes never leave the outer transaction.

    Bound with `join_transaction_mode="create_savepoint"` so a test that
    triggers an IntegrityError (and thus an implicit session rollback,
    e.g. inside `pytest.raises`) rolls back to a SAVEPOINT rather than
    invalidating the outer transaction this fixture rolls back at
    teardown.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()
