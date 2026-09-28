"""_parse_rating is pure/deterministic once the model call is mocked —
see ADR-0025.
"""
from app.agent.quality import _parse_rating


def test_parses_a_bare_number():
    assert _parse_rating("5") == 5


def test_parses_after_rating_prefix():
    assert _parse_rating("some preamble rating: 3") == 3


def test_parses_first_valid_number_when_rambling():
    assert _parse_rating("i would rate this a 4 out of 5") == 4


def test_returns_none_for_unparseable_input():
    assert _parse_rating("excellent reply") is None
    assert _parse_rating("") is None


def test_returns_none_for_out_of_range_number():
    assert _parse_rating("9") is None
    assert _parse_rating("0") is None
