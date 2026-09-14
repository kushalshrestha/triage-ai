import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 768  # provisional, see ADR-0004 — revisit once ai-architecture.md's embedding model is chosen


class KnowledgeDoc(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_docs"

    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    chunks: Mapped[list["DocChunk"]] = relationship(
        back_populates="knowledge_doc", cascade="all, delete-orphan"
    )


class DocChunk(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "doc_chunks"
    __table_args__ = (UniqueConstraint("knowledge_doc_id", "chunk_index"),)

    knowledge_doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_docs.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    knowledge_doc: Mapped["KnowledgeDoc"] = relationship(back_populates="chunks")
