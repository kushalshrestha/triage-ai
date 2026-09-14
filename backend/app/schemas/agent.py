import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import DecisionType


class AgentDecisionRead(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    decision_type: DecisionType
    model_used: str
    confidence_score: float | None
    reasoning: str | None
    created_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}
