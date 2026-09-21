import logging
import uuid

from sqlalchemy.orm import Session

from app.models import DocChunk, KnowledgeDoc, KnowledgeDocStatus
from app.rag.chunking import chunk_text
from app.rag.contextualize import ContextualizationProvider, generate_chunk_context
from app.rag.embeddings import embed_texts

logger = logging.getLogger(__name__)


def create_pending_knowledge_doc(db: Session, title: str, source: str | None, content: str) -> KnowledgeDoc:
    """Fast path: persist the `KnowledgeDoc` row itself (status
    `PROCESSING`) without chunking/embedding, so a caller — the
    `POST /knowledge` router — can return immediately regardless of
    document size and hand the slow work to `process_knowledge_doc()`,
    run in the background (see ADR-0017).
    """
    doc = KnowledgeDoc(title=title, source=source, content=content, status=KnowledgeDocStatus.PROCESSING)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def process_knowledge_doc(
    db: Session,
    doc_id: uuid.UUID,
    use_contextual_retrieval: bool = False,
    contextualization_provider: ContextualizationProvider = "ollama",
    completed_status: KnowledgeDocStatus = KnowledgeDocStatus.PENDING_REVIEW,
) -> KnowledgeDoc:
    """Chunk, (optionally) contextualize, embed, and persist chunks for
    an already-created `KnowledgeDoc` (see `create_pending_knowledge_doc`).
    Ends in `completed_status` (default `PENDING_REVIEW`) on success, or
    `FAILED` (an exception during chunking/embedding, caught and
    recorded rather than left as a stuck `PROCESSING` row) — see
    ADR-0017.

    `use_contextual_retrieval` is opt-in and defaults to False so every
    existing call site is unaffected — see ADR-0015. It only actually
    triggers when the document produced more than one chunk; a single
    chunk already contains 100% of its own context, so contextualizing
    it would be pure cost for zero benefit even if the caller opts in.

    `contextualization_provider` picks how the chunk-context blurb is
    generated (see `app.rag.contextualize.generate_chunk_context`).
    Measured against the same golden set (ADR-0015): no contextualization
    and `"ollama"` tied for best (MRR@3 = 0.90); `"claude"` measured
    slightly worse (0.87, and costs real money); `"heuristic"` (title +
    position, no model call) measured worst (0.80) — its blurb is
    near-identical boilerplate across every chunk of the same document,
    which dilutes each chunk's own distinguishing signal rather than
    adding any. Default is `"ollama"`: free, and the only contextualizing
    option that didn't measure worse than doing nothing.
    """
    doc = db.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise ValueError(f"KnowledgeDoc {doc_id} not found")

    try:
        chunks = chunk_text(doc.content)
        if chunks:
            contextualize = use_contextual_retrieval and len(chunks) > 1
            context_prefixes: list[str | None] = [None] * len(chunks)

            if contextualize:
                total_input_tokens = 0
                total_output_tokens = 0
                for i, chunk_content in enumerate(chunks):
                    context, usage = generate_chunk_context(
                        doc.content,
                        chunk_content,
                        provider=contextualization_provider,
                        title=doc.title,
                        chunk_index=i,
                        total_chunks=len(chunks),
                    )
                    context_prefixes[i] = context
                    if usage is not None:
                        total_input_tokens += usage.input_tokens
                        total_output_tokens += usage.output_tokens
                logger.info(
                    "contextual retrieval: doc=%r chunks=%d provider=%s claude_input_tokens=%d "
                    "claude_output_tokens=%d",
                    doc.title,
                    len(chunks),
                    contextualization_provider,
                    total_input_tokens,
                    total_output_tokens,
                )

            texts_to_embed = [
                f"{prefix}\n\n{chunk_content}" if prefix else chunk_content
                for prefix, chunk_content in zip(context_prefixes, chunks)
            ]
            embeddings = embed_texts(texts_to_embed)

            for index, (chunk_content, prefix, embedding) in enumerate(
                zip(chunks, context_prefixes, embeddings)
            ):
                db.add(
                    DocChunk(
                        knowledge_doc_id=doc.id,
                        chunk_index=index,
                        content=chunk_content,
                        context_prefix=prefix,
                        embedding=embedding,
                    )
                )

        doc.status = completed_status
    except Exception:
        logger.exception("failed to process knowledge doc %s (title=%r)", doc_id, doc.title)
        doc.status = KnowledgeDocStatus.FAILED

    db.commit()
    db.refresh(doc)
    return doc


def ingest_document(
    db: Session,
    title: str,
    source: str | None,
    content: str,
    use_contextual_retrieval: bool = False,
    contextualization_provider: ContextualizationProvider = "ollama",
) -> KnowledgeDoc:
    """Synchronous convenience wrapper: create the doc, then process it
    immediately in the same call — the same external behavior this
    function has always had. Every test/eval across Phases 9-13 calls
    this directly and expects chunks to exist, searchable, as soon as
    it returns — so unlike `POST /knowledge` (the staff-facing, less-
    trusted upload path the review gate in ADR-0017 exists for), this
    marks the doc `APPROVED` directly rather than `PENDING_REVIEW`.
    `ingest_document()` is the trusted, direct-call path (seed scripts,
    evals); the review queue is specifically for documents arriving
    through the HTTP API.
    """
    doc = create_pending_knowledge_doc(db, title=title, source=source, content=content)
    return process_knowledge_doc(
        db,
        doc.id,
        use_contextual_retrieval=use_contextual_retrieval,
        contextualization_provider=contextualization_provider,
        completed_status=KnowledgeDocStatus.APPROVED,
    )
