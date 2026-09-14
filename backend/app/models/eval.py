import enum

from sqlalchemy import Boolean, Enum, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class GoldenSetSource(str, enum.Enum):
    SYNTHETIC = "synthetic"
    REAL = "real"


class EvalRunType(str, enum.Enum):
    CLASSIFICATION = "classification"
    FAITHFULNESS = "faithfulness"
    JUDGE = "judge"
    SAFETY = "safety"
    RETRIEVAL = "retrieval"  # added ADR-0010: recall@k has no home in the original 4
    ROUTING = "routing"  # added ADR-0010: auto_respond/draft/escalate accuracy


class GoldenSetEntry(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "golden_set"

    ticket_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_label: Mapped[str] = mapped_column(String, nullable=False)
    expected_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[GoldenSetSource] = mapped_column(
        Enum(GoldenSetSource, name="golden_set_source"),
        nullable=False,
        default=GoldenSetSource.SYNTHETIC,
    )


class EvalRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "eval_runs"

    run_type: Mapped[EvalRunType] = mapped_column(
        Enum(EvalRunType, name="eval_run_type"), nullable=False
    )
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
