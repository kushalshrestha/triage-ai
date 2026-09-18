import logging

from sqlalchemy.orm import Session

from app.models import DocChunk, KnowledgeDoc
from app.rag.chunking import chunk_text
from app.rag.contextualize import ContextualizationProvider, generate_chunk_context
from app.rag.embeddings import embed_texts

logger = logging.getLogger(__name__)


def ingest_document(
    db: Session,
    title: str,
    source: str | None,
    content: str,
    use_contextual_retrieval: bool = False,
    contextualization_provider: ContextualizationProvider = "ollama",
) -> KnowledgeDoc:
    """Chunk, (optionally) contextualize, embed, and persist a document.

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
    doc = KnowledgeDoc(title=title, source=source, content=content)
    db.add(doc)
    db.flush()

    chunks = chunk_text(content)
    if chunks:
        contextualize = use_contextual_retrieval and len(chunks) > 1
        context_prefixes: list[str | None] = [None] * len(chunks)

        if contextualize:
            total_input_tokens = 0
            total_output_tokens = 0
            for i, chunk_content in enumerate(chunks):
                context, usage = generate_chunk_context(
                    content,
                    chunk_content,
                    provider=contextualization_provider,
                    title=title,
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
                title,
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

    db.commit()
    db.refresh(doc)
    return doc
