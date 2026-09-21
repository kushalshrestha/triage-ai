from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.config import get_settings
from app.models import DocChunk


@lru_cache
def _get_reranker() -> CrossEncoder:
    return CrossEncoder(get_settings().reranker_model_name)


def rerank_candidates(
    query_text: str, candidates: list[tuple[DocChunk, float]]
) -> list[tuple[DocChunk, float]]:
    """Re-order a small candidate set by cross-encoder relevance (see
    ADR-0016). Unlike the bi-encoder embeddings used for the initial
    vector search, a cross-encoder scores (query, chunk) as one joint
    input — better at fine-grained disambiguation between
    near-duplicate candidates, but not indexable, so it only ever runs
    over the already-narrowed candidate list, never the full corpus.

    Returns the same `(chunk, cosine_similarity)` tuples, just
    reordered — the cross-encoder's own score (an unbounded logit, not
    a 0-1 value) is used only to decide order and is never returned as
    "the score." `app/agent/orchestrator.py`'s routing thresholds and
    the `CHECK (0<=x<=1)` columns on `retrievals`/`agent_decisions`
    are calibrated against real cosine similarity — the same invariant
    already established for hybrid search (ADR-0013) and contextual
    retrieval (ADR-0015).
    """
    if not candidates:
        return candidates

    model = _get_reranker()
    pairs = [(query_text, chunk.content) for chunk, _similarity in candidates]
    cross_scores = model.predict(pairs)

    ranked = sorted(
        zip(candidates, cross_scores), key=lambda pair: pair[1], reverse=True
    )
    return [candidate for candidate, _cross_score in ranked]
