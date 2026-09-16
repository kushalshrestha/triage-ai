"""add full text search index to doc_chunks

Revision ID: 2fe7f6fa8e01
Revises: 9ba978e63e78
Create Date: 2026-09-16 02:59:30.477889

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2fe7f6fa8e01' # pragma: allowlist secret
down_revision: Union[str, None] = '9ba978e63e78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Functional GIN index over doc_chunks.content for the keyword side of
    # hybrid retrieval (see ADR-0013) — plain op.create_index() can't express
    # an index over to_tsvector(...) of a column, so this is raw DDL.
    op.execute(
        "CREATE INDEX ix_doc_chunks_content_fts "
        "ON doc_chunks USING GIN (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_doc_chunks_content_fts")
