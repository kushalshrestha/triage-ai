import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import AgentDecision
    from app.models.guardrail import GuardrailCheck
    from app.models.user import User


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ESCALATED = "escalated"


class TicketEventType(str, enum.Enum):
    CREATED = "created"
    COMMENT_ADDED = "comment_added"
    STATUS_CHANGED = "status_changed"
    DRAFT_GENERATED = "draft_generated"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class Ticket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tickets"

    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status"), nullable=False, default=TicketStatus.OPEN
    )

    requester: Mapped["User"] = relationship(
        back_populates="tickets", foreign_keys=[requester_id]
    )
    assigned_agent: Mapped["User | None"] = relationship(foreign_keys=[assigned_agent_id])
    events: Mapped[list["TicketEvent"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
    agent_decisions: Mapped[list["AgentDecision"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
    guardrail_checks: Mapped[list["GuardrailCheck"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class TicketEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ticket_events"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[TicketEventType] = mapped_column(
        Enum(TicketEventType, name="ticket_event_type"), nullable=False
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="events")
    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_id])
