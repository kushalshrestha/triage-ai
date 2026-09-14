import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.knowledge import DocChunk
    from app.models.ticket import Ticket


class DecisionType(str, enum.Enum):
    AUTO_RESPOND = "auto_respond"
    DRAFT_FOR_REVIEW = "draft_for_review"
    ESCALATE = "escalate"


class AgentDecision(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "agent_decisions"
    __table_args__ = (
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_agent_decisions_confidence_score_range",
        ),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    decision_type: Mapped[DecisionType] = mapped_column(
        Enum(DecisionType, name="decision_type"), nullable=False
    )
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claude_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claude_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="agent_decisions")
    retrievals: Mapped[list["Retrieval"]] = relationship(
        back_populates="agent_decision", cascade="all, delete-orphan"
    )


class Retrieval(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "retrievals"
    __table_args__ = (
        UniqueConstraint("agent_decision_id", "doc_chunk_id"),
        CheckConstraint(
            "similarity_score >= 0 AND similarity_score <= 1",
            name="ck_retrievals_similarity_score_range",
        ),
    )

    agent_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_decisions.id", ondelete="CASCADE"), nullable=False
    )
    doc_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_chunks.id", ondelete="CASCADE"), nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    agent_decision: Mapped["AgentDecision"] = relationship(back_populates="retrievals")
    doc_chunk: Mapped["DocChunk"] = relationship()
