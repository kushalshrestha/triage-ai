"""decide_outcome is pure (no model/DB), tested in isolation from the
rest of run_triage per ADR-0008.
"""
import pytest

from app.agent.orchestrator import decide_outcome
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
