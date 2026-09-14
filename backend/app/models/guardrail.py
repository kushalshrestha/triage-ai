import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import AgentDecision
    from app.models.ticket import Ticket


class GuardrailStage(str, enum.Enum):
    INPUT = "input"
    OUTPUT = "output"


class GuardrailCheckType(str, enum.Enum):
    INJECTION = "injection"
    PII_REDACTION = "pii_redaction"
    SCHEMA_VALIDATION = "schema_validation"
    GROUNDEDNESS = "groundedness"
    CONFIDENCE_THRESHOLD = "confidence_threshold"


class GuardrailCheck(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "guardrail_checks"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    agent_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_decisions.id", ondelete="CASCADE"), nullable=True
    )
    stage: Mapped[GuardrailStage] = mapped_column(
        Enum(GuardrailStage, name="guardrail_stage"), nullable=False
    )
    check_type: Mapped[GuardrailCheckType] = mapped_column(
        Enum(GuardrailCheckType, name="guardrail_check_type"), nullable=False
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="guardrail_checks")
    agent_decision: Mapped["AgentDecision | None"] = relationship()
