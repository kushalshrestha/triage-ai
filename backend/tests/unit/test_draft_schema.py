import pytest
from pydantic import ValidationError

from app.agent.drafting import DraftOutput


def test_valid_draft_parses():
    draft = DraftOutput.model_validate(
        {"reply_text": "Here's how to reset your password.", "cited_chunk_indices": [0, 2]}
    )
    assert draft.reply_text == "Here's how to reset your password."
    assert draft.cited_chunk_indices == [0, 2]


def test_missing_reply_text_rejected():
    with pytest.raises(ValidationError):
        DraftOutput.model_validate({"cited_chunk_indices": [0]})


def test_non_list_cited_chunk_indices_rejected():
    with pytest.raises(ValidationError):
        DraftOutput.model_validate({"reply_text": "hello", "cited_chunk_indices": "not-a-list"})


def test_empty_cited_chunk_indices_is_valid():
    draft = DraftOutput.model_validate({"reply_text": "hello", "cited_chunk_indices": []})
    assert draft.cited_chunk_indices == []
