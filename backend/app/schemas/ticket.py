import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import TicketEventType, TicketStatus


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


class TicketRead(BaseModel):
    id: uuid.UUID
    requester_id: uuid.UUID
    requester_email: str
    assigned_agent_id: uuid.UUID | None
    subject: str
    body: str
    status: TicketStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TicketStatusUpdate(BaseModel):
    status: TicketStatus | None = None
    assigned_agent_id: uuid.UUID | None = None


class TicketEventCreate(BaseModel):
    body: str = Field(min_length=1)


class TicketEventRead(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    actor_id: uuid.UUID | None
    event_type: TicketEventType
    payload: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
