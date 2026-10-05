"""Direct tests of generate_draft()'s own validation logic, mocking the
Anthropic client at the boundary (app.agent.drafting.Anthropic).

Before this file, none of these checks had direct test coverage —
every existing test (tests/integration/test_agent_triage_api.py) mocks
orchestrator.generate_draft itself, bypassing generate_draft's
internals entirely. See ADR-0019.

As of ADR-0027, generate_draft() takes `subject`/`body` strings
directly rather than a `Ticket` object — it has no access to raw
ticket fields at all, so it can't repeat the PII-redaction bug that
ADR found (redaction happened for retrieval/classification but not for
the drafting call). `test_prompt_uses_exactly_the_passed_in_subject_and_body`
below is the direct regression test for that: it proves the string
that reaches the Claude client is the caller's string, verbatim, with
no further (or missing) transformation inside this function.
"""
from unittest.mock import MagicMock

from types import SimpleNamespace

import pytest

from app.agent import drafting
from app.agent.drafting import DraftSchemaError, generate_draft

SUBJECT = "Forgot my password"
BODY = "I can't log in."
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

    draft, usage = generate_draft(
        SUBJECT, BODY, ["Password reset instructions."], ACCOUNT_CONTEXT
    )

    assert draft.reply_text == "Reset it here."
    assert draft.cited_chunk_indices == [0]
    assert usage.input_tokens == 100
    assert usage.output_tokens == 20


def test_prompt_uses_exactly_the_passed_in_subject_and_body(monkeypatch):
    """ADR-0027: generate_draft must send exactly what its caller passes
    in — no raw Ticket access, so the caller's redaction (or lack of
    it) is the only thing that determines what Claude sees.
    """
    client = _mock_client({"reply_text": "Reset it here.", "cited_chunk_indices": [0]})
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    generate_draft(
        "[REDACTED_EMAIL] follow-up",
        "Please email me at [REDACTED_EMAIL].",
        ["Password reset instructions."],
        ACCOUNT_CONTEXT,
    )

    sent_message = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "[REDACTED_EMAIL] follow-up" in sent_message
    assert "Please email me at [REDACTED_EMAIL]." in sent_message


def test_out_of_range_citation_raises(monkeypatch):
    client = _mock_client({"reply_text": "Reset it here.", "cited_chunk_indices": [5]})
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    with pytest.raises(DraftSchemaError, match="outside the provided context"):
        generate_draft(SUBJECT, BODY, ["Password reset instructions."], ACCOUNT_CONTEXT)


def test_empty_citations_with_context_raises(monkeypatch):
    client = _mock_client({"reply_text": "Reset it here.", "cited_chunk_indices": []})
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    with pytest.raises(DraftSchemaError, match="cited no context"):
        generate_draft(SUBJECT, BODY, ["Password reset instructions."], ACCOUNT_CONTEXT)


def test_empty_citations_allowed_when_no_context(monkeypatch):
    client = _mock_client({"reply_text": "I don't have enough info.", "cited_chunk_indices": []})
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    draft, _usage = generate_draft(SUBJECT, BODY, [], ACCOUNT_CONTEXT)

    assert draft.cited_chunk_indices == []


def test_missing_tool_call_raises(monkeypatch):
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=100, output_tokens=20), content=[]
    )
    client = MagicMock()
    client.messages.create.return_value = response
    monkeypatch.setattr(drafting, "Anthropic", MagicMock(return_value=client))

    with pytest.raises(DraftSchemaError, match="did not call"):
        generate_draft(SUBJECT, BODY, ["Password reset instructions."], ACCOUNT_CONTEXT)
