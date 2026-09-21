import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import KnowledgeDocStatus


class KnowledgeDocCreate(BaseModel):
    title: str = Field(min_length=1)
    source: str | None = None
    content: str = Field(min_length=1)


class KnowledgeDocRead(BaseModel):
    id: uuid.UUID
    title: str
    source: str | None
    content: str
    status: KnowledgeDocStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class ChunkSearchResult(BaseModel):
    chunk_id: uuid.UUID
    knowledge_doc_id: uuid.UUID
    knowledge_doc_title: str
    content: str
    similarity_score: float
