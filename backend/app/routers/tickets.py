import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import STAFF_ROLES, get_current_user, require_role
from app.models import Ticket, TicketEvent, TicketEventType, User
from app.schemas import TicketCreate, TicketEventCreate, TicketEventRead, TicketRead, TicketStatusUpdate

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _get_ticket_or_404(ticket_id: uuid.UUID, db: Session) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


def _ensure_can_view_ticket(ticket: Ticket, current_user: User) -> None:
    is_staff = current_user.role.value in STAFF_ROLES
    is_owner = ticket.requester_id == current_user.id
    if not (is_staff or is_owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your ticket")


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Ticket:
    ticket = Ticket(requester_id=current_user.id, subject=payload.subject, body=payload.body)
    db.add(ticket)
    db.flush()
    db.add(
        TicketEvent(
            ticket_id=ticket.id, actor_id=current_user.id, event_type=TicketEventType.CREATED
        )
    )
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("", response_model=list[TicketRead])
def list_tickets(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[Ticket]:
    query = db.query(Ticket).options(joinedload(Ticket.requester))
    if current_user.role.value not in STAFF_ROLES:
        query = query.filter(Ticket.requester_id == current_user.id)
    return query.order_by(Ticket.created_at.desc()).all()


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Ticket:
    ticket = _get_ticket_or_404(ticket_id, db)
    _ensure_can_view_ticket(ticket, current_user)
    return ticket


@router.patch("/{ticket_id}", response_model=TicketRead)
def update_ticket(
    ticket_id: uuid.UUID,
    payload: TicketStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*STAFF_ROLES)),
) -> Ticket:
    ticket = _get_ticket_or_404(ticket_id, db)

    if payload.status is not None and payload.status != ticket.status:
        db.add(
            TicketEvent(
                ticket_id=ticket.id,
                actor_id=current_user.id,
                event_type=TicketEventType.STATUS_CHANGED,
                payload={"from": ticket.status.value, "to": payload.status.value},
            )
        )
        ticket.status = payload.status

    if payload.assigned_agent_id is not None:
        ticket.assigned_agent_id = payload.assigned_agent_id

    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/{ticket_id}/events", response_model=list[TicketEventRead])
def list_ticket_events(
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketEvent]:
    ticket = _get_ticket_or_404(ticket_id, db)
    _ensure_can_view_ticket(ticket, current_user)
    return (
        db.query(TicketEvent)
        .filter(TicketEvent.ticket_id == ticket.id)
        .order_by(TicketEvent.created_at.asc())
        .all()
    )


@router.post(
    "/{ticket_id}/events", response_model=TicketEventRead, status_code=status.HTTP_201_CREATED
)
def add_ticket_comment(
    ticket_id: uuid.UUID,
    payload: TicketEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketEvent:
    ticket = _get_ticket_or_404(ticket_id, db)
    _ensure_can_view_ticket(ticket, current_user)

    event = TicketEvent(
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.COMMENT_ADDED,
        payload={"body": payload.body},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
