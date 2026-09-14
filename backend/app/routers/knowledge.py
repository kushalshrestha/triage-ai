from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import STAFF_ROLES, get_current_user, require_role
from app.models import KnowledgeDoc, User
from app.rag.ingestion import ingest_document
from app.rag.retrieval import retrieve_relevant_chunks
from app.schemas import ChunkSearchResult, KnowledgeDocCreate, KnowledgeDocRead

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("", response_model=KnowledgeDocRead, status_code=status.HTTP_201_CREATED)
def create_knowledge_doc(
    payload: KnowledgeDocCreate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(*STAFF_ROLES)),
) -> KnowledgeDoc:
    return ingest_document(db, title=payload.title, source=payload.source, content=payload.content)


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
