import time

from sqlalchemy.orm import Session

from app.agent.classify import classify_ticket_with_fallback
from app.agent.drafting import ClaudeUsage, DraftOutput, DraftSchemaError, generate_draft
from app.agent.judge import assess_groundedness
from app.agent.tools import get_account_context
from app.config import get_settings
from app.guardrails.injection import is_likely_injection
from app.guardrails.pii import redact_pii
from app.models import (
    AgentDecision,
    DecisionType,
    GuardrailCheck,
    GuardrailCheckType,
    GuardrailStage,
    Retrieval,
    Ticket,
    TicketEvent,
    TicketEventType,
    TicketStatus,
)
from app.rag.retrieval import retrieve_relevant_chunks


def decide_outcome(top_similarity: float | None) -> DecisionType:
    """Pure routing logic, kept separate from run_triage so it's testable
    without any model or DB involved. See ADR-0008 for why retrieval
    similarity drives this instead of a second Ollama call.
    """
    settings = get_settings()
    if top_similarity is None or top_similarity < settings.draft_confidence_threshold:
        return DecisionType.ESCALATE
    if top_similarity < settings.auto_respond_confidence_threshold:
        return DecisionType.DRAFT_FOR_REVIEW
    return DecisionType.AUTO_RESPOND


def _clamp_similarity(value: float) -> float:
    """retrievals.similarity_score and agent_decisions.confidence_score
    both CHECK (0 <= x <= 1); pgvector cosine similarity is mathematically
    in [-1, 1], so clamp before persisting.
    """
    return max(0.0, min(1.0, value))


def citation_meets_confidence_bar(decision_type: DecisionType, min_cited_similarity: float) -> bool:
    """Pure, kept separate like decide_outcome() — see ADR-0021.

    `top_similarity` (the top-*retrieved* chunk) drives the initial
    routing decision before drafting happens; this checks whether the
    chunk(s) actually cited still clear the bar that decision implied,
    using the same thresholds. `min_cited_similarity` is the weakest of
    the cited chunks — a reply is only as trustworthy as its weakest
    citation.
    """
    settings = get_settings()
    threshold = (
        settings.auto_respond_confidence_threshold
        if decision_type == DecisionType.AUTO_RESPOND
        else settings.draft_confidence_threshold
    )
    return min_cited_similarity >= threshold


def run_triage(db: Session, ticket: Ticket) -> AgentDecision:
    start_time = time.monotonic()
    raw_text = f"{ticket.subject}\n{ticket.body}"

    injection_detected = is_likely_injection(raw_text)
    db.add(
        GuardrailCheck(
            ticket_id=ticket.id,
            stage=GuardrailStage.INPUT,
            check_type=GuardrailCheckType.INJECTION,
            passed=not injection_detected,
        )
    )

    if injection_detected:
        decision = AgentDecision(
            ticket_id=ticket.id,
            decision_type=DecisionType.ESCALATE,
            model_used="none",
            confidence_score=0.0,
            reasoning="Input guardrail: prompt injection detected in ticket text.",
            total_latency_ms=int((time.monotonic() - start_time) * 1000),
        )
        db.add(decision)
        _apply_decision_to_ticket(db, ticket, decision)
        db.commit()
        db.refresh(decision)
        return decision

    redacted_text = redact_pii(raw_text)
    db.add(
        GuardrailCheck(
            ticket_id=ticket.id,
            stage=GuardrailStage.INPUT,
            check_type=GuardrailCheckType.PII_REDACTION,
            passed=(redacted_text == raw_text),
            details={"redacted": redacted_text != raw_text},
        )
    )

    settings = get_settings()
    retrieved = retrieve_relevant_chunks(db, query_text=redacted_text, k=3)
    top_similarity = _clamp_similarity(retrieved[0][1]) if retrieved else None

    category, used_claude_for_classification = classify_ticket_with_fallback(redacted_text)
    decision_type = decide_outcome(top_similarity)
    # Captured before schema/groundedness can change decision_type below,
    # so this guardrail row reflects what it actually checked: retrieval
    # confidence, not downstream draft quality.
    routing_passed = decision_type != DecisionType.ESCALATE

    models_used: list[str] = [f"ollama/{settings.ollama_model_name}"]
    # A classification fallback (ADR-0023) is a real Claude API call
    # even when this ticket never reaches drafting (e.g. it escalates
    # on retrieval similarity alone) — model_used must reflect it.
    if used_claude_for_classification:
        models_used.append(settings.claude_model_name)

    draft: DraftOutput | None = None
    schema_valid: bool | None = None
    schema_error: str | None = None
    groundedness_passed: bool | None = None
    groundedness_raw: str | None = None
    claude_usage: ClaudeUsage | None = None
    min_cited_similarity: float | None = None
    citation_confidence_passed: bool | None = None

    if decision_type in (DecisionType.DRAFT_FOR_REVIEW, DecisionType.AUTO_RESPOND):
        account_context = get_account_context(db, ticket.requester)
        context_texts = [chunk.content for chunk, _score in retrieved]

        if settings.claude_model_name not in models_used:
            models_used.append(settings.claude_model_name)

        try:
            draft, claude_usage = generate_draft(ticket, context_texts, account_context)
            schema_valid = True
        except DraftSchemaError as exc:
            schema_valid = False
            schema_error = str(exc)
            claude_usage = exc.usage
            decision_type = DecisionType.ESCALATE

        if draft is not None:
            # Checked against only the chunks the draft actually cites,
            # not the whole retrieved pool — see ADR-0019. Otherwise a
            # reply could cite chunk 0 while really drawing on chunk 2,
            # and still look "grounded" because *something* in the pool
            # happens to support it. generate_draft() guarantees
            # cited_chunk_indices is non-empty whenever context_texts is.
            cited_texts = [context_texts[i] for i in draft.cited_chunk_indices]
            groundedness_passed, groundedness_raw = assess_groundedness(
                draft.reply_text, cited_texts
            )
            if not groundedness_passed and decision_type == DecisionType.AUTO_RESPOND:
                decision_type = DecisionType.DRAFT_FOR_REVIEW

            # Post-draft confidence check — see ADR-0021. top_similarity
            # drove the initial routing decision before drafting; this
            # reconciles it against what was actually cited, since the
            # two can differ (confirmed live in Phase 16: the top-
            # retrieved chunk wasn't always the one Claude cited).
            min_cited_similarity = min(
                _clamp_similarity(retrieved[i][1]) for i in draft.cited_chunk_indices
            )
            citation_confidence_passed = citation_meets_confidence_bar(
                decision_type, min_cited_similarity
            )
            if not citation_confidence_passed and decision_type == DecisionType.AUTO_RESPOND:
                decision_type = DecisionType.DRAFT_FOR_REVIEW

    reasoning_parts = [
        f"classified as '{category}'" + (" (Claude fallback)" if used_claude_for_classification else ""),
        f"top retrieval similarity={top_similarity:.2f}" if top_similarity is not None else "no retrieval match",
    ]
    if schema_valid is False:
        reasoning_parts.append(f"draft schema validation failed: {schema_error}")
    if groundedness_passed is not None:
        reasoning_parts.append(
            "groundedness=passed" if groundedness_passed else "groundedness=failed (downgraded from auto_respond)"
        )
    if citation_confidence_passed is not None:
        reasoning_parts.append(
            f"citation confidence={'passed' if citation_confidence_passed else 'failed'} "
            f"(min cited similarity={min_cited_similarity:.2f})"
        )

    decision = AgentDecision(
        ticket_id=ticket.id,
        decision_type=decision_type,
        model_used=",".join(models_used),
        confidence_score=top_similarity,
        reasoning="; ".join(reasoning_parts),
        total_latency_ms=int((time.monotonic() - start_time) * 1000),
        claude_input_tokens=claude_usage.input_tokens if claude_usage else None,
        claude_output_tokens=claude_usage.output_tokens if claude_usage else None,
    )
    db.add(decision)
    db.flush()

    # `rank` (1-based here) maps back to `draft.cited_chunk_indices`
    # (0-based) because both are derived from this same `retrieved`
    # list, in this same order, within this one function call — that
    # invariant is what makes `rank - 1 in draft.cited_chunk_indices`
    # correct. Don't reorder or re-fetch `retrieved` between here and
    # where `context_texts` was built above without preserving it.
    for rank, (chunk, score) in enumerate(retrieved, start=1):
        db.add(
            Retrieval(
                agent_decision_id=decision.id,
                doc_chunk_id=chunk.id,
                similarity_score=_clamp_similarity(score),
                rank=rank,
                cited=draft is not None and (rank - 1) in draft.cited_chunk_indices,
            )
        )

    db.add(
        GuardrailCheck(
            ticket_id=ticket.id,
            agent_decision_id=decision.id,
            stage=GuardrailStage.OUTPUT,
            check_type=GuardrailCheckType.CONFIDENCE_THRESHOLD,
            passed=routing_passed,
            details={
                "top_similarity": top_similarity,
                "draft_threshold": settings.draft_confidence_threshold,
                "auto_respond_threshold": settings.auto_respond_confidence_threshold,
            },
        )
    )

    if schema_valid is not None:
        db.add(
            GuardrailCheck(
                ticket_id=ticket.id,
                agent_decision_id=decision.id,
                stage=GuardrailStage.OUTPUT,
                check_type=GuardrailCheckType.SCHEMA_VALIDATION,
                passed=schema_valid,
                details={"error": schema_error} if schema_error else None,
            )
        )

    if groundedness_passed is not None:
        db.add(
            GuardrailCheck(
                ticket_id=ticket.id,
                agent_decision_id=decision.id,
                stage=GuardrailStage.OUTPUT,
                check_type=GuardrailCheckType.GROUNDEDNESS,
                passed=groundedness_passed,
                details={"judge_raw_verdict": groundedness_raw},
            )
        )

    if citation_confidence_passed is not None:
        db.add(
            GuardrailCheck(
                ticket_id=ticket.id,
                agent_decision_id=decision.id,
                stage=GuardrailStage.OUTPUT,
                check_type=GuardrailCheckType.CITATION_CONFIDENCE,
                passed=citation_confidence_passed,
                details={"min_cited_similarity": min_cited_similarity},
            )
        )

    if draft is not None and schema_valid:
        citations = [
            {
                "knowledge_doc_title": retrieved[i][0].knowledge_doc.title,
                "content": retrieved[i][0].content,
                "similarity_score": _clamp_similarity(retrieved[i][1]),
            }
            for i in draft.cited_chunk_indices
        ]
        db.add(
            TicketEvent(
                ticket_id=ticket.id,
                event_type=TicketEventType.DRAFT_GENERATED,
                payload={
                    "reply_text": draft.reply_text,
                    "cited_chunk_indices": draft.cited_chunk_indices,
                    "citations": citations,
                    "decision_type": decision_type.value,
                    "grounded": groundedness_passed,
                },
            )
        )

    _apply_decision_to_ticket(db, ticket, decision)

    db.commit()
    db.refresh(decision)
    return decision


def _apply_decision_to_ticket(db: Session, ticket: Ticket, decision: AgentDecision) -> None:
    if decision.decision_type == DecisionType.ESCALATE:
        ticket.status = TicketStatus.ESCALATED
        db.add(TicketEvent(ticket_id=ticket.id, event_type=TicketEventType.ESCALATED))
    elif decision.decision_type == DecisionType.DRAFT_FOR_REVIEW:
        ticket.status = TicketStatus.PENDING
    elif decision.decision_type == DecisionType.AUTO_RESPOND:
        ticket.status = TicketStatus.RESOLVED
        db.add(TicketEvent(ticket_id=ticket.id, event_type=TicketEventType.RESOLVED))
