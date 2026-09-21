import logging
import uuid
from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, get_session_factory
from app.dependencies import STAFF_ROLES, get_current_user, require_role
from app.models import KnowledgeDoc, KnowledgeDocStatus, User, UserRole
from app.rag.ingestion import create_pending_knowledge_doc, process_knowledge_doc
from app.rag.retrieval import retrieve_relevant_chunks
from app.rate_limit import rate_limit
from app.schemas import ChunkSearchResult, KnowledgeDocCreate, KnowledgeDocRead

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


def _process_in_background(session_factory: Callable[[], Session], doc_id: uuid.UUID) -> None:
    """Runs after the response is sent (see ADR-0017) — opens its own
    session via `session_factory` rather than reusing the request's
    (closed by the time this runs). `contextualization_provider`/
    `use_contextual_retrieval` stay at their defaults here; this router
    doesn't expose them as request fields, matching current behavior.
    """
    db = session_factory()
    try:
        process_knowledge_doc(db, doc_id)
    finally:
        db.close()


@router.post("", response_model=KnowledgeDocRead, status_code=status.HTTP_201_CREATED)
def create_knowledge_doc(
    payload: KnowledgeDocCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    session_factory: Callable[[], Session] = Depends(get_session_factory),
    _current_user: User = Depends(require_role(*STAFF_ROLES)),
    _rate_limit: None = Depends(
        rate_limit("knowledge-ingest", get_settings().knowledge_ingest_rate_limit_per_minute, 60)
    ),
) -> KnowledgeDoc:
    doc = create_pending_knowledge_doc(db, title=payload.title, source=payload.source, content=payload.content)
    background_tasks.add_task(_process_in_background, session_factory, doc.id)
    return doc


@router.get("", response_model=list[KnowledgeDocRead])
def list_knowledge_docs(
    db: Session = Depends(get_db), _current_user: User = Depends(get_current_user)
) -> list[KnowledgeDoc]:
    return db.query(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc()).all()


@router.get("/search", response_model=list[ChunkSearchResult])
def search_knowledge(
    q: str = Query(min_length=1),
    k: int = Query(default=3, ge=1, le=20),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
    _rate_limit: None = Depends(
        rate_limit("knowledge-search", get_settings().knowledge_search_rate_limit_per_minute, 60)
    ),
) -> list[ChunkSearchResult]:
    results = retrieve_relevant_chunks(db, query_text=q, k=k)
    return [
        ChunkSearchResult(
            chunk_id=chunk.id,
            knowledge_doc_id=chunk.knowledge_doc_id,
            knowledge_doc_title=chunk.knowledge_doc.title,
            content=chunk.content,
            similarity_score=score,
        )
        for chunk, score in results
    ]


def _transition_status(
    db: Session, knowledge_doc_id: uuid.UUID, target: KnowledgeDocStatus
) -> KnowledgeDoc:
    doc = db.get(KnowledgeDoc, knowledge_doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge doc not found")
    if doc.status != KnowledgeDocStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Knowledge doc is {doc.status.value}, not pending_review",
        )
    doc.status = target
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/{knowledge_doc_id}/approve", response_model=KnowledgeDocRead)
def approve_knowledge_doc(
    knowledge_doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.ADMIN.value)),
) -> KnowledgeDoc:
    return _transition_status(db, knowledge_doc_id, KnowledgeDocStatus.APPROVED)


@router.post("/{knowledge_doc_id}/reject", response_model=KnowledgeDocRead)
def reject_knowledge_doc(
    knowledge_doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.ADMIN.value)),
) -> KnowledgeDoc:
    return _transition_status(db, knowledge_doc_id, KnowledgeDocStatus.REJECTED)


@router.delete("/{knowledge_doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_doc(
    knowledge_doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(*STAFF_ROLES)),
) -> None:
    doc = db.get(KnowledgeDoc, knowledge_doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge doc not found")
    db.delete(doc)
    db.commit()
