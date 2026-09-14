# ADR-0011: Knowledge document deletion

**Status:** Accepted
**Date:** 2026-09-14

## Context
Phase 3 built ingestion but never deletion — there was no way to
remove a knowledge document once created. Building a management UI
surfaces this gap directly: staff need to be able to fix a mistake
(wrong content, outdated doc) without a database console.

`doc_chunks.knowledge_doc_id` is `ON DELETE CASCADE` (ADR-0004), and
`retrievals.doc_chunk_id` is also `ON DELETE CASCADE` (ADR-0004). That
means deleting a `KnowledgeDoc` cascades to its chunks, and
transitively to any `retrievals` rows that cited those chunks in a past
triage decision — quietly erasing part of that decision's audit trail,
in tension with `docs/results.md`'s "every decision is fully recorded"
framing.

## Decision
Hard delete. `DELETE /knowledge/{id}` removes the `KnowledgeDoc`, its
`doc_chunks`, and any `retrievals` rows that cited them, via the
existing cascade rules — no new column, no soft-delete flag. Accepted
knowingly: this is a portfolio-scale project without real
audit-compliance requirements, and adding an `is_active`/`deleted_at`
column (plus updating every query that lists/searches chunks to filter
on it) is a bigger schema change than a "remove a bad doc" feature
justifies right now.

Staff-only (`require_role`), same authz as ingestion (ADR-0007) — the
threat this restricts isn't just "who can poison the knowledge base"
but now also "who can quietly erase it."

## Alternatives considered
- **Soft delete (`is_active` / `deleted_at`)** — preserves audit
  history and lets the eval/retrieval-quality story stay fully intact
  even after a doc is "removed" from active search. The more correct
  long-term design, but real added scope: every place that queries
  `doc_chunks` (retrieval, ingestion count checks) needs an
  `is_active` filter, and it's not clear yet whether anyone actually
  needs to look at deleted-doc history. Revisit if that need shows up.
- **Block deletion of docs with retrieval history** — protects the
  audit trail without a schema change, but makes the feature nearly
  useless in practice: once a doc has been used even once, it becomes
  permanently undeletable, defeating the "fix a mistake" purpose this
  feature exists for.

## Consequences
- Deleting a knowledge doc is irreversible and can remove data that
  `docs/results.md` describes as fully recorded — the UI's delete
  confirmation should say so plainly, not just "are you sure?"
- If audit-compliance requirements ever become real (not just a
  portfolio demo), this decision needs revisiting before it matters —
  tracked here rather than assumed away.
