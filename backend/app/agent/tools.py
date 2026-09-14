from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Ticket, User


def get_account_context(db: Session, user: User) -> dict:
    """The agent's one tool call beyond retrieval (see ADR-0008) — real
    account data already in the schema, not a fabricated SLA/billing
    lookup.
    """
    account_age_days = (datetime.now(timezone.utc) - user.created_at).days
    prior_ticket_count = db.query(Ticket).filter(Ticket.requester_id == user.id).count()
    return {"account_age_days": account_age_days, "prior_ticket_count": prior_ticket_count}
