import pytest

from app.rag.chunking import chunk_text


def test_empty_string_returns_no_chunks():
    assert chunk_text("") == []


def test_whitespace_only_returns_no_chunks():
    assert chunk_text("   \n\t  ") == []


def test_short_text_returns_single_chunk():
    text = "This is a short FAQ answer."
    assert chunk_text(text, chunk_size=800, overlap=100) == [text]


def test_text_exactly_chunk_size_returns_single_chunk():
    text = "a" * 800
    chunks = chunk_text(text, chunk_size=800, overlap=100)
    assert chunks == [text]


def test_long_text_splits_into_overlapping_chunks():
    text = "a" * 700 + "b" * 700  # 1400 chars
    chunks = chunk_text(text, chunk_size=800, overlap=100)
    assert len(chunks) == 2
    assert chunks[0] == text[0:800]
    assert chunks[1] == text[700:1400]
    # the overlap region is identical between consecutive chunks
    assert chunks[0][-100:] == chunks[1][:100]


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=100, overlap=100)
