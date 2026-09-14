from app.agent.judge import _parse_verdict


def test_parses_yes_answer_as_grounded():
    assert _parse_verdict("answer: yes.") is True


def test_parses_no_answer_as_not_grounded():
    assert _parse_verdict("answer: no.") is False


def test_handles_bare_yes_without_answer_prefix():
    assert _parse_verdict("yes") is True


def test_unparseable_response_fails_safe_to_not_grounded():
    assert _parse_verdict("I'm not sure how to answer that") is False


def test_empty_response_fails_safe_to_not_grounded():
    assert _parse_verdict("") is False
