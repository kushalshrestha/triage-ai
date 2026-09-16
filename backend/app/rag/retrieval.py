import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import DocChunk
from app.rag.embeddings import embed_texts

# Candidate pool fetched from each side before fusion — wider than the
# final k so RRF has real material to reorder. RRF_K=60 is the standard
# default from the original Reciprocal Rank Fusion paper. See ADR-0013.
CANDIDATE_POOL = 10
RRF_K = 60


def _cosine_similarity(query_embedding: list[float], chunk_embedding: list[float] | None) -> float:
    if chunk_embedding is None:
        return 0.0
    a = np.asarray(query_embedding, dtype=float)
    b = np.asarray(chunk_embedding, dtype=float)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def retrieve_relevant_chunks(
    db: Session, query_text: str, k: int = 3
) -> list[tuple[DocChunk, float]]:
    """Top-k chunks for query_text via hybrid search: vector similarity
    (pgvector cosine distance) and Postgres full-text search, fused with
    Reciprocal Rank Fusion (see ADR-0013).

    The returned float is always the chunk's real cosine similarity to
    the query, in [0, 1] — RRF only decides which chunks are selected
    and in what order, never what the "score" means downstream.
    app/agent/orchestrator.py feeds this value directly into its routing
    thresholds (ADR-0008), and it's written to `retrievals.similarity_score`
    / `agent_decisions.confidence_score`, both `CHECK (0<=x<=1)` columns
    calibrated against real cosine similarity — never the RRF fusion
    score, which lives on a different, much smaller scale.

    Standalone building block for this phase (see ADR-0007) — does not
    persist to `retrievals`, which is scoped to an `agent_decision_id`
    that doesn't exist until phase 5's agent orchestration.
    """
    query_embedding = embed_texts([query_text])[0]
    distance = DocChunk.embedding.cosine_distance(query_embedding)

    vector_rows = (
        db.query(DocChunk)
        .options(joinedload(DocChunk.knowledge_doc))
        .filter(DocChunk.embedding.isnot(None))
        .order_by(distance)
        .limit(CANDIDATE_POOL)
        .all()
    )

    ts_vector = func.to_tsvector("english", DocChunk.content)
    ts_query = func.plainto_tsquery("english", query_text)
    keyword_rows = (
        db.query(DocChunk)
        .options(joinedload(DocChunk.knowledge_doc))
        .filter(ts_vector.op("@@")(ts_query))
        .order_by(func.ts_rank(ts_vector, ts_query).desc())
        .limit(CANDIDATE_POOL)
        .all()
    )

    rrf_scores: dict = {}
    chunks_by_id: dict = {}
    for rank, chunk in enumerate(vector_rows, start=1):
        rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + 1.0 / (RRF_K + rank)
        chunks_by_id[chunk.id] = chunk
    for rank, chunk in enumerate(keyword_rows, start=1):
        rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + 1.0 / (RRF_K + rank)
        chunks_by_id[chunk.id] = chunk

    ranked_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)[:k]
    return [
        (
            chunks_by_id[cid],
            _cosine_similarity(query_embedding, chunks_by_id[cid].embedding),
        )
        for cid in ranked_ids
    ]
