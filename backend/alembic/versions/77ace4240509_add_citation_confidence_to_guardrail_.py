"""add citation_confidence to guardrail_check_type

Revision ID: 77ace4240509
Revises: 307a48b91d03
Create Date: 2026-09-22 01:47:40.658028

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '77ace4240509'  # pragma: allowlist secret
down_revision: Union[str, None] = '307a48b91d03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic doesn't autodetect Postgres enum VALUE additions (only
    # new/removed types) — hand-written, same as 9ba978e63e78. Label
    # must be UPPERCASE to match the existing convention (ADR-0010):
    # SQLAlchemy's Enum type binds Python enum members by .name, not
    # .value, and every existing guardrail_check_type label already is.
    op.execute("ALTER TYPE guardrail_check_type ADD VALUE IF NOT EXISTS 'CITATION_CONFIDENCE'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Recreate the type
    # without the added value — fails if any row actually uses it,
    # which is fine: this migration lands in the same phase that first
    # starts writing citation_confidence checks at all.
    op.execute("ALTER TYPE guardrail_check_type RENAME TO guardrail_check_type_old")
    op.execute(
        "CREATE TYPE guardrail_check_type AS ENUM "
        "('INJECTION', 'PII_REDACTION', 'SCHEMA_VALIDATION', 'GROUNDEDNESS', 'CONFIDENCE_THRESHOLD')"
    )
    op.execute(
        "ALTER TABLE guardrail_checks ALTER COLUMN check_type TYPE guardrail_check_type "
        "USING check_type::text::guardrail_check_type"
    )
    op.execute("DROP TYPE guardrail_check_type_old")
