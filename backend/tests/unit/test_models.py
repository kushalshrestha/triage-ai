"""Constraint and relationship tests for the schema in app/models/.

Deterministic checks against a real (test) Postgres — no model calls
involved, so this belongs in tests/unit per testing-strategy.md, not
tests/evals.
"""
import pytest
from sqlalchemy.exc import DataError, IntegrityError

from app.models import (
    AgentDecision,
    DecisionType,
    DocChunk,
    EvalRun,
    EvalRunType,
    GoldenSetEntry,
    GuardrailCheck,
    GuardrailCheckType,
    GuardrailStage,
    KnowledgeDoc,
    Retrieval,
    Ticket,
    TicketEvent,
    TicketEventType,
    TicketStatus,
    User,
    UserRole,
)


def make_user(db_session, email="user@example.com", role=UserRole.CUSTOMER) -> User:
    user = User(email=email, hashed_password="hashed", role=role)
    db_session.add(user)
    db_session.flush()
    return user


def make_ticket(db_session, requester=None, **kwargs) -> Ticket:
    requester = requester or make_user(db_session)
    ticket = Ticket(
        requester_id=requester.id,
        subject=kwargs.pop("subject", "Login broken"),
        body=kwargs.pop("body", "Can't log in since the reset."),
        **kwargs,
    )
    db_session.add(ticket)
    db_session.flush()
    return ticket


class TestUser:
    def test_defaults_role_to_customer(self, db_session):
        user = make_user(db_session)
        assert user.role == UserRole.CUSTOMER
        assert user.created_at is not None

    def test_email_must_be_unique(self, db_session):
        make_user(db_session, email="dupe@example.com")
        db_session.add(User(email="dupe@example.com", hashed_password="x"))
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_rejects_invalid_role(self, db_session):
        db_session.add(User(email="bad-role@example.com", hashed_password="x", role="wizard"))
        with pytest.raises((DataError, LookupError)):
            db_session.flush()


class TestTicket:
    def test_defaults_status_to_open(self, db_session):
        ticket = make_ticket(db_session)
        assert ticket.status == TicketStatus.OPEN

    def test_requester_relationship(self, db_session):
        requester = make_user(db_session, email="requester@example.com")
        ticket = make_ticket(db_session, requester=requester)
        assert ticket.requester is requester
        assert ticket in requester.tickets

    def test_rejects_invalid_status(self, db_session):
        ticket = make_ticket(db_session)
        ticket.status = "not_a_status"
        with pytest.raises((DataError, LookupError)):
            db_session.flush()

    def test_deleting_requester_is_restricted(self, db_session):
        requester = make_user(db_session, email="restrict-me@example.com")
        make_ticket(db_session, requester=requester)
        db_session.delete(requester)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_deleting_ticket_cascades_to_events(self, db_session):
        ticket = make_ticket(db_session)
        db_session.add(
            TicketEvent(ticket_id=ticket.id, event_type=TicketEventType.CREATED, actor_id=None)
        )
        db_session.flush()

        db_session.delete(ticket)
        db_session.flush()

        remaining = db_session.query(TicketEvent).filter_by(ticket_id=ticket.id).all()
        assert remaining == []

    def test_deleting_ticket_cascades_to_agent_decisions(self, db_session):
        ticket = make_ticket(db_session)
        decision = AgentDecision(
            ticket_id=ticket.id, decision_type=DecisionType.AUTO_RESPOND, model_used="claude"
        )
        db_session.add(decision)
        db_session.flush()

        db_session.delete(ticket)
        db_session.flush()

        remaining = db_session.query(AgentDecision).filter_by(ticket_id=ticket.id).all()
        assert remaining == []


class TestTicketEvent:
    def test_actor_id_nullable_for_system_events(self, db_session):
        ticket = make_ticket(db_session)
        event = TicketEvent(
            ticket_id=ticket.id, event_type=TicketEventType.DRAFT_GENERATED, actor_id=None
        )
        db_session.add(event)
        db_session.flush()
        assert event.actor_id is None

    def test_payload_round_trips_json(self, db_session):
        ticket = make_ticket(db_session)
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=TicketEventType.STATUS_CHANGED,
            payload={"from": "open", "to": "resolved"},
        )
        db_session.add(event)
        db_session.flush()
        db_session.expire(event)
        assert event.payload == {"from": "open", "to": "resolved"}


class TestKnowledgeAndChunks:
    def test_deleting_doc_cascades_to_chunks(self, db_session):
        doc = KnowledgeDoc(title="Password reset FAQ", content="...")
        db_session.add(doc)
        db_session.flush()
        chunk = DocChunk(knowledge_doc_id=doc.id, chunk_index=0, content="Reset your password by")
        db_session.add(chunk)
        db_session.flush()

        db_session.delete(doc)
        db_session.flush()

        remaining = db_session.query(DocChunk).filter_by(knowledge_doc_id=doc.id).all()
        assert remaining == []

    def test_chunk_index_unique_per_doc(self, db_session):
        doc = KnowledgeDoc(title="Billing FAQ", content="...")
        db_session.add(doc)
        db_session.flush()
        db_session.add(DocChunk(knowledge_doc_id=doc.id, chunk_index=0, content="first"))
        db_session.flush()
        db_session.add(DocChunk(knowledge_doc_id=doc.id, chunk_index=0, content="duplicate index"))
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_embedding_round_trips(self, db_session):
        doc = KnowledgeDoc(title="Refunds FAQ", content="...")
        db_session.add(doc)
        db_session.flush()
        vector = [0.1] * 768
        chunk = DocChunk(
            knowledge_doc_id=doc.id, chunk_index=0, content="refund policy", embedding=vector
        )
        db_session.add(chunk)
        db_session.flush()
        db_session.expire(chunk)
        assert list(chunk.embedding) == pytest.approx(vector)


class TestAgentDecision:
    def test_model_used_is_required(self, db_session):
        ticket = make_ticket(db_session)
        db_session.add(
            AgentDecision(ticket_id=ticket.id, decision_type=DecisionType.ESCALATE, model_used=None)
        )
        with pytest.raises(IntegrityError):
            db_session.flush()

    @pytest.mark.parametrize("bad_score", [-0.01, 1.01])
    def test_confidence_score_out_of_range_rejected(self, db_session, bad_score):
        ticket = make_ticket(db_session)
        db_session.add(
            AgentDecision(
                ticket_id=ticket.id,
                decision_type=DecisionType.DRAFT_FOR_REVIEW,
                model_used="ollama/llama3",
                confidence_score=bad_score,
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_confidence_score_in_range_accepted(self, db_session):
        ticket = make_ticket(db_session)
        decision = AgentDecision(
            ticket_id=ticket.id,
            decision_type=DecisionType.AUTO_RESPOND,
            model_used="ollama/llama3",
            confidence_score=0.87,
        )
        db_session.add(decision)
        db_session.flush()
        assert decision.confidence_score == 0.87


class TestRetrieval:
    def test_links_decision_to_chunk_with_score_and_rank(self, db_session):
        ticket = make_ticket(db_session)
        decision = AgentDecision(
            ticket_id=ticket.id, decision_type=DecisionType.DRAFT_FOR_REVIEW, model_used="claude"
        )
        doc = KnowledgeDoc(title="FAQ", content="...")
        db_session.add_all([decision, doc])
        db_session.flush()
        chunk = DocChunk(knowledge_doc_id=doc.id, chunk_index=0, content="answer")
        db_session.add(chunk)
        db_session.flush()

        retrieval = Retrieval(
            agent_decision_id=decision.id, doc_chunk_id=chunk.id, similarity_score=0.92, rank=1
        )
        db_session.add(retrieval)
        db_session.flush()

        assert retrieval.agent_decision is decision
        assert retrieval.doc_chunk is chunk

    def test_similarity_score_out_of_range_rejected(self, db_session):
        ticket = make_ticket(db_session)
        decision = AgentDecision(
            ticket_id=ticket.id, decision_type=DecisionType.DRAFT_FOR_REVIEW, model_used="claude"
        )
        doc = KnowledgeDoc(title="FAQ", content="...")
        db_session.add_all([decision, doc])
        db_session.flush()
        chunk = DocChunk(knowledge_doc_id=doc.id, chunk_index=0, content="answer")
        db_session.add(chunk)
        db_session.flush()

        db_session.add(
            Retrieval(agent_decision_id=decision.id, doc_chunk_id=chunk.id, similarity_score=1.5, rank=1)
        )
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_duplicate_chunk_per_decision_rejected(self, db_session):
        ticket = make_ticket(db_session)
        decision = AgentDecision(
            ticket_id=ticket.id, decision_type=DecisionType.DRAFT_FOR_REVIEW, model_used="claude"
        )
        doc = KnowledgeDoc(title="FAQ", content="...")
        db_session.add_all([decision, doc])
        db_session.flush()
        chunk = DocChunk(knowledge_doc_id=doc.id, chunk_index=0, content="answer")
        db_session.add(chunk)
        db_session.flush()

        db_session.add(
            Retrieval(agent_decision_id=decision.id, doc_chunk_id=chunk.id, similarity_score=0.9, rank=1)
        )
        db_session.flush()
        db_session.add(
            Retrieval(agent_decision_id=decision.id, doc_chunk_id=chunk.id, similarity_score=0.8, rank=2)
        )
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestGuardrailCheck:
    def test_input_stage_check_has_no_agent_decision(self, db_session):
        ticket = make_ticket(db_session)
        check = GuardrailCheck(
            ticket_id=ticket.id,
            stage=GuardrailStage.INPUT,
            check_type=GuardrailCheckType.INJECTION,
            passed=True,
        )
        db_session.add(check)
        db_session.flush()
        assert check.agent_decision_id is None

    def test_output_stage_check_attaches_to_decision(self, db_session):
        ticket = make_ticket(db_session)
        decision = AgentDecision(
            ticket_id=ticket.id, decision_type=DecisionType.AUTO_RESPOND, model_used="claude"
        )
        db_session.add(decision)
        db_session.flush()

        check = GuardrailCheck(
            ticket_id=ticket.id,
            agent_decision_id=decision.id,
            stage=GuardrailStage.OUTPUT,
            check_type=GuardrailCheckType.GROUNDEDNESS,
            passed=False,
            details={"unsupported_claims": 2},
        )
        db_session.add(check)
        db_session.flush()
        db_session.expire(check)
        assert check.agent_decision is decision
        assert check.details == {"unsupported_claims": 2}

    def test_deleting_ticket_cascades_to_guardrail_checks(self, db_session):
        ticket = make_ticket(db_session)
        db_session.add(
            GuardrailCheck(
                ticket_id=ticket.id,
                stage=GuardrailStage.INPUT,
                check_type=GuardrailCheckType.PII_REDACTION,
                passed=True,
            )
        )
        db_session.flush()

        db_session.delete(ticket)
        db_session.flush()

        remaining = db_session.query(GuardrailCheck).filter_by(ticket_id=ticket.id).all()
        assert remaining == []


class TestGoldenSetAndEvalRuns:
    def test_matches_existing_golden_set_jsonl_fields(self, db_session):
        entry = GoldenSetEntry(
            ticket_text="I was charged twice for my subscription this month.",
            expected_label="billing",
        )
        db_session.add(entry)
        db_session.flush()
        assert entry.source.value == "synthetic"

    def test_eval_run_records_score_against_threshold(self, db_session):
        run = EvalRun(
            run_type=EvalRunType.CLASSIFICATION,
            model_used="ollama/llama3",
            score=0.93,
            threshold=0.90,
            passed=True,
        )
        db_session.add(run)
        db_session.flush()
        assert run.passed is True
