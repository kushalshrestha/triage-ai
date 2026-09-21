import enum
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2, see ADR-0007


class KnowledgeDocStatus(str, enum.Enum):
    """See ADR-0017. PROCESSING and FAILED are the two states of the
    background chunk/embed step; PENDING_REVIEW/APPROVED/REJECTED are
    the source-review workflow closing threat-model item #8. Only
    APPROVED docs are visible to `retrieve_relevant_chunks()`.
    """

    PROCESSING = "processing"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class KnowledgeDoc(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_docs"

    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Python-side default mirrors the migration's DB-level backfill
    # default for pre-existing rows (already-trusted content shouldn't
    # vanish from search) — real ingestion always sets this explicitly
    # (see app/rag/ingestion.py), this is just the safe fallback.
    status: Mapped[KnowledgeDocStatus] = mapped_column(
        Enum(KnowledgeDocStatus, name="knowledge_doc_status"),
        nullable=False,
        default=KnowledgeDocStatus.APPROVED,
    )

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
    # Contextual-retrieval blurb prepended to `content` before embedding
    # (see ADR-0015) — never shown to users/cited, kept separate from
    # `content` on purpose. Null unless ingestion opted in.
    context_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)

    knowledge_doc: Mapped["KnowledgeDoc"] = relationship(back_populates="chunks")
