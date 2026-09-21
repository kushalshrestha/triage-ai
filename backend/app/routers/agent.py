import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agent.orchestrator import run_triage
from app.config import get_settings
from app.database import get_db
from app.dependencies import STAFF_ROLES, require_role
from app.models import AgentDecision, Ticket, User
from app.rate_limit import rate_limit
from app.schemas import AgentDecisionRead

router = APIRouter(prefix="/tickets", tags=["agent"])


@router.post("/{ticket_id}/triage", response_model=AgentDecisionRead, status_code=status.HTTP_201_CREATED)
def trigger_triage(
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(*STAFF_ROLES)),
    _rate_limit: None = Depends(
        rate_limit("triage", get_settings().triage_rate_limit_per_minute, 60)
    ),
) -> AgentDecision:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return run_triage(db, ticket)
