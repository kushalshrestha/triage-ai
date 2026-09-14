"""Checks the fixed local embedding model's deterministic properties
(shape, determinism) — not exact output values, since a real model is
involved. See ADR-0007: this is a deterministic local model with no
sampling, so it's tested here rather than in tests/evals/.
"""
from app.rag.embeddings import embed_texts


def test_embedding_has_expected_dimension():
    vectors = embed_texts(["password reset instructions"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 384


def test_embedding_is_deterministic():
    text = "how do I update my billing address"
    first = embed_texts([text])[0]
    second = embed_texts([text])[0]
    assert first == second


def test_different_texts_produce_different_embeddings():
    vectors = embed_texts(["reset my password", "refund my subscription"])
    assert vectors[0] != vectors[1]


def test_embeds_batch_in_order():
    texts = ["alpha document", "beta document", "gamma document"]
    batch = embed_texts(texts)
    singles = [embed_texts([t])[0] for t in texts]
    assert batch == singles
