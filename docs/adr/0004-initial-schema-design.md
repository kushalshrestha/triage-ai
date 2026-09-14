# ADR-0004: Initial relational schema design

**Status:** Accepted
**Date:** 2026-09-13

## Context
`docs/system-architecture.md` names the ten tables the platform needs
(`users`, `tickets`, `ticket_events`, `knowledge_docs`, `doc_chunks`,
`agent_decisions`, `retrievals`, `guardrail_checks`, `golden_set`,
`eval_runs`) and calls out two specific requirements —
`agent_decisions.model_used` must be logged, and `guardrail_checks` must
be its own table rather than a boolean flag — but defers column-level
detail to an ERD (`docs/schema.md` / "the diagram from planning") that
was never actually committed to the repo. Implementing the Alembic
migration and SQLAlchemy models therefore requires making a set of
schema decisions that aren't written down anywhere yet.

## Decision
1. **UUID (v4, app-generated) primary keys on every table**, instead of
   serial integers. `tickets` and `users` are the two tables most exposed
   to end users; sequential integer IDs make ticket/account enumeration
   trivial (IDOR-adjacent, see `docs/threat-model.md` threat #3). UUIDs
   cost a little index size, buy a little safety by default.
2. **Native Postgres enums** for closed-vocabulary columns: `users.role`,
   `tickets.status`, `ticket_events.event_type`,
   `agent_decisions.decision_type`, `guardrail_checks.stage` /
   `check_type`, `eval_runs.run_type`, `golden_set.source`. These
   vocabularies are fixed by the architecture docs (e.g. the agent's
   decision space is explicitly "auto-respond / draft-for-review /
   escalate" per `ai-architecture.md`) and enum columns make invalid
   values a constraint violation instead of a code-review nit.
3. **`doc_chunks.embedding` is `vector(768)`.** `ai-architecture.md`
   still lists the embedding model as TBD, so this dimension is
   provisional — 768 matches a common local embedding model
   (Ollama `nomic-embed-text`) consistent with the project's
   local-model-for-routine-work approach. Revisit this column (a new
   migration) once the embedding model is actually chosen and recorded
   in `ai-architecture.md`, the same way ADR-0002 already flags
   embedding volume as a later revisit.
4. **`guardrail_checks` carries `ticket_id` (always set) plus a nullable
   `agent_decision_id`.** Input-side checks (injection detection, PII
   redaction) run on ticket text before any agent decision exists, so
   `agent_decision_id` is null for those rows. Output-side checks (schema
   validation, groundedness, confidence threshold) validate a specific
   draft and attach to the `agent_decisions` row that produced it.
5. **`retrievals` links `agent_decision_id` ↔ `doc_chunk_id`** with a
   `similarity_score` and `rank`, giving every decision an auditable,
   queryable list of what grounded it. This is the table the RAG
   faithfulness eval (`ai-architecture.md`) reads from.
6. **Cascade rules:** deleting a `ticket` cascades to its
   `ticket_events`, `agent_decisions`, `guardrail_checks`, and (via
   `agent_decisions`) `retrievals` — none of those rows mean anything
   without the ticket. Deleting a `user` does **not** cascade-delete
   their tickets (`ON DELETE RESTRICT` on `tickets.requester_id`); ticket
   history has to survive account deletion per the repudiation mitigation
   in `docs/threat-model.md` (threat #7 — need a record of what happened
   and by which model, independent of account lifecycle).

## Alternatives considered
- **Serial integer PKs** — simpler, smaller indexes, but reintroduces the
  IDOR-by-enumeration risk the threat model already flags; rejected.
- **Free-text `status`/`role`/etc. columns validated only in application
  code** — less migration overhead, but pushes a correctness guarantee
  that the DB can enforce cheaply back onto every call site; rejected.
- **A single `model_calls` table instead of splitting `agent_decisions`
  vs `guardrail_checks` vs `retrievals`** — would match "one row per LLM
  call" more literally, but conflates three different concerns (what the
  agent decided, what grounded it, whether guardrails passed) that
  `system-architecture.md` already describes as separate pipeline stages
  and that the eval framework needs to query independently. Rejected in
  favor of matching the documented pipeline shape.
- **Leaving `doc_chunks.embedding` dimension unset until the embedding
  model is chosen** — pgvector requires a fixed dimension per column;
  can't defer this without blocking the migration entirely. Picked a
  reasonable default and flagged it provisional instead.

## Consequences
- Model code and the migration in `backend/alembic/versions/` embed these
  choices; changing the embedding dimension later is a new migration
  (`ALTER COLUMN ... TYPE vector(N)`), not a breaking rewrite, but it does
  require re-embedding every existing `doc_chunks` row.
- Enum columns mean adding a new ticket status or decision type later is
  itself a migration (`ALTER TYPE ... ADD VALUE`), not just a code
  change — an intentional tradeoff for catching typos/invalid states at
  the DB layer.
- `docs/system-architecture.md`'s dangling reference to a separate ERD
  file is effectively superseded by this ADR plus the model code itself;
  no separate `docs/schema.md` is being introduced.
