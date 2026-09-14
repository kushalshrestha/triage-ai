"""add retrieval and routing to eval_run_type

Revision ID: 9ba978e63e78
Revises: afd9d13f8952
Create Date: 2026-09-14 13:51:53.345744

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9ba978e63e78'
down_revision: Union[str, None] = 'afd9d13f8952'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic doesn't autodetect Postgres enum VALUE additions (only
    # new/removed types), so this is hand-written. Labels must be
    # UPPERCASE to match the existing convention: SQLAlchemy's Enum
    # type binds Python enum members by .name, not .value, and the
    # original migration's 4 labels ('CLASSIFICATION', etc.) are
    # already uppercase — confirmed by querying pg_enum directly after
    # a lowercase version of this migration silently corrupted the dev
    # DB's casing during its own downgrade/upgrade round-trip test.
    op.execute("ALTER TYPE eval_run_type ADD VALUE IF NOT EXISTS 'RETRIEVAL'")
    op.execute("ALTER TYPE eval_run_type ADD VALUE IF NOT EXISTS 'ROUTING'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Recreate the type
    # without the two added values — fails if any row actually uses
    # them, which is fine: this migration lands in the same phase that
    # first starts writing eval_runs rows at all.
    op.execute("ALTER TYPE eval_run_type RENAME TO eval_run_type_old")
    op.execute(
        "CREATE TYPE eval_run_type AS ENUM "
        "('CLASSIFICATION', 'FAITHFULNESS', 'JUDGE', 'SAFETY')"
    )
    op.execute(
        "ALTER TABLE eval_runs ALTER COLUMN run_type TYPE eval_run_type "
        "USING run_type::text::eval_run_type"
    )
    op.execute("DROP TYPE eval_run_type_old")
