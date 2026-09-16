"""add context_prefix to doc_chunks

Revision ID: b24f71c17ec8
Revises: 2fe7f6fa8e01
Create Date: 2026-09-16 04:51:32.869843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b24f71c17ec8' # pragma: allowlist secret
down_revision: Union[str, None] = '2fe7f6fa8e01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("doc_chunks", sa.Column("context_prefix", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("doc_chunks", "context_prefix")
