"""Direct tests of generate_draft()'s own validation logic, mocking the
Anthropic client at the boundary (app.agent.drafting.Anthropic).

Before this file, none of these checks had direct test coverage —
every existing test (tests/integration/test_agent_triage_api.py) mocks
orchestrator.generate_draft itself, bypassing generate_draft's
internals entirely. See ADR-0019.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agent import drafting
from app.agent.drafting import DraftSchemaError, generate_draft

TICKET = SimpleNamespace(subject="Forgot my password", body="I can't log in.")
ACCOUNT_CONTEXT = {"prior_ticket_count": 0, "account_age_days": 10}


def _mock_client(tool_input: dict) -> MagicMock:
    tool_use_block = SimpleNamespace(type="tool_use", input=tool_input)
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        content=[tool_use_block],
    )
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_valid_citation_returns_draft(monkeypatch):
    client = _mock_client({"reply_text": "Reset it here.", "cited_chunk_indices": [0]})
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    draft, usage = generate_draft(TICKET, ["Password reset instructions."], ACCOUNT_CONTEXT)

    assert draft.reply_text == "Reset it here."
    assert draft.cited_chunk_indices == [0]
    assert usage.input_tokens == 100
    assert usage.output_tokens == 20


def test_out_of_range_citation_raises(monkeypatch):
    client = _mock_client({"reply_text": "Reset it here.", "cited_chunk_indices": [5]})
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    with pytest.raises(DraftSchemaError, match="outside the provided context"):
        generate_draft(TICKET, ["Password reset instructions."], ACCOUNT_CONTEXT)


def test_empty_citations_with_context_raises(monkeypatch):
    client = _mock_client({"reply_text": "Reset it here.", "cited_chunk_indices": []})
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    with pytest.raises(DraftSchemaError, match="cited no context"):
        generate_draft(TICKET, ["Password reset instructions."], ACCOUNT_CONTEXT)


def test_empty_citations_allowed_when_no_context(monkeypatch):
    client = _mock_client({"reply_text": "I don't have enough info.", "cited_chunk_indices": []})
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    draft, _usage = generate_draft(TICKET, [], ACCOUNT_CONTEXT)

    assert draft.cited_chunk_indices == []


def test_missing_tool_call_raises(monkeypatch):
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=100, output_tokens=20), content=[]
    )
    client = MagicMock()
    client.messages.create.return_value = response
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    with pytest.raises(DraftSchemaError, match="did not call"):
        generate_draft(TICKET, ["Password reset instructions."], ACCOUNT_CONTEXT)
