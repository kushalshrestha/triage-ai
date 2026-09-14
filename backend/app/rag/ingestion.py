from sqlalchemy.orm import Session

from app.models import DocChunk, KnowledgeDoc
from app.rag.chunking import chunk_text
from app.rag.embeddings import embed_texts


def ingest_document(db: Session, title: str, source: str | None, content: str) -> KnowledgeDoc:
    doc = KnowledgeDoc(title=title, source=source, content=content)
    db.add(doc)
    db.flush()

    chunks = chunk_text(content)
    if chunks:
        embeddings = embed_texts(chunks)
        for index, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
            db.add(
                DocChunk(
                    knowledge_doc_id=doc.id,
                    chunk_index=index,
                    content=chunk_content,
                    embedding=embedding,
                )
            )

    db.commit()
    db.refresh(doc)
    return doc
