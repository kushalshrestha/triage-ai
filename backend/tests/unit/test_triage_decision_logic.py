"""decide_outcome and citation_meets_confidence_bar are pure (no
model/DB), tested in isolation from the rest of run_triage per
ADR-0008 and ADR-0021.
"""
import pytest

from app.agent.orchestrator import citation_meets_confidence_bar, decide_outcome
from app.config import get_settings
from app.models import DecisionType

settings = get_settings()
DRAFT = settings.draft_confidence_threshold
AUTO = settings.auto_respond_confidence_threshold


def test_no_retrieval_result_escalates():
    assert decide_outcome(None) == DecisionType.ESCALATE


@pytest.mark.parametrize("similarity", [0.0, DRAFT - 0.01])
def test_below_draft_threshold_escalates(similarity):
    assert decide_outcome(similarity) == DecisionType.ESCALATE


@pytest.mark.parametrize("similarity", [DRAFT, (DRAFT + AUTO) / 2, AUTO - 0.01])
def test_between_thresholds_drafts_for_review(similarity):
    assert decide_outcome(similarity) == DecisionType.DRAFT_FOR_REVIEW


@pytest.mark.parametrize("similarity", [AUTO, 1.0])
def test_at_or_above_auto_threshold_auto_responds(similarity):
    assert decide_outcome(similarity) == DecisionType.AUTO_RESPOND


@pytest.mark.parametrize("similarity", [AUTO, 1.0])
def test_citation_at_or_above_auto_threshold_passes_for_auto_respond(similarity):
    assert citation_meets_confidence_bar(DecisionType.AUTO_RESPOND, similarity) is True


@pytest.mark.parametrize("similarity", [0.0, DRAFT, AUTO - 0.01])
def test_citation_below_auto_threshold_fails_for_auto_respond(similarity):
    assert citation_meets_confidence_bar(DecisionType.AUTO_RESPOND, similarity) is False


@pytest.mark.parametrize("similarity", [DRAFT, AUTO, 1.0])
def test_citation_at_or_above_draft_threshold_passes_for_draft_for_review(similarity):
    assert citation_meets_confidence_bar(DecisionType.DRAFT_FOR_REVIEW, similarity) is True


@pytest.mark.parametrize("similarity", [0.0, DRAFT - 0.01])
def test_citation_below_draft_threshold_fails_for_draft_for_review(similarity):
    assert citation_meets_confidence_bar(DecisionType.DRAFT_FOR_REVIEW, similarity) is False
