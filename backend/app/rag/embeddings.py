from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import get_settings


@lru_cache
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(get_settings().embedding_model_name)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of strings with the configured local model.

    Deterministic given a fixed model (no sampling), so this is treated
    as ordinary deterministic code for testing purposes — see
    tests/unit/test_embeddings.py.
    """
    model = _get_model()
    embeddings = model.encode(texts, convert_to_numpy=True)
    return embeddings.tolist()
