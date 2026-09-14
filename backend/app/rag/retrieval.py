from sqlalchemy.orm import Session, joinedload

from app.models import DocChunk
from app.rag.embeddings import embed_texts


def retrieve_relevant_chunks(
    db: Session, query_text: str, k: int = 3
) -> list[tuple[DocChunk, float]]:
    """Top-k most similar chunks to query_text, with similarity in [0, 1].

    Standalone building block for this phase (see ADR-0007) — does not
    persist to `retrievals`, which is scoped to an `agent_decision_id`
    that doesn't exist until phase 5's agent orchestration.
    """
    query_embedding = embed_texts([query_text])[0]
    distance = DocChunk.embedding.cosine_distance(query_embedding)

    rows = (
        db.query(DocChunk, distance.label("distance"))
        .options(joinedload(DocChunk.knowledge_doc))
        .filter(DocChunk.embedding.isnot(None))
        .order_by(distance)
        .limit(k)
        .all()
    )
    return [(chunk, 1 - dist) for chunk, dist in rows]
