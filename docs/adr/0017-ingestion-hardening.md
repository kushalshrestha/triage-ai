# ADR-0017: Knowledge ingestion hardening — background processing + source review

**Status:** Accepted
**Date:** 2026-09-21

## Context
Two real, long-standing gaps, flagged early in this phase and left
open while Phases 9-13 focused on retrieval quality:

1. **Synchronous ingestion blocks the request for the full
   chunk/embed pipeline.** `POST /knowledge` called `ingest_document()`
   inline, so a large document held the request open for the entire
   chunk → (optional contextualize) → embed → persist sequence.
2. **`docs/threat-model.md` item #8** (Spoofing): "Malicious document
   injected into the knowledge base during ingestion, poisoning
   retrieval" — mitigation "Ingestion source allowlist / review step
   before a doc enters `knowledge_docs`," status "Open question — not
   yet designed."

**A `max_length` cap on document content was considered first and
rejected.** The initial draft of this work proposed bounding worst-case
synchronous latency with a fixed content-length limit (measured: a
200,000-character document embeds in ~8.7s). Correctly rejected: a
client's legitimate document can be arbitrarily large, so a fixed cap
isn't the right mitigation for gap 1 — it just relocates the problem to
whatever size was chosen, and an unbounded document really can block a
request for a long time. That removed the premise for treating
background processing as unnecessary, so this ADR makes it the actual
fix for gap 1, and it's used for gap 2 as well as it now naturally fits.

**Chosen mechanism, verified before committing to it — not assumed:**
FastAPI's built-in `BackgroundTasks`. A sync task passed to it runs in
a threadpool *after* the response is sent, so it doesn't block the
event loop for other concurrent requests. Its real, honestly-stated
limits: no durability across a process restart/crash (an in-flight
task is simply lost), no retry, and enough concurrent large ingestions
could exhaust the threadpool and degrade unrelated request latency. A
real task queue (Celery/arq/RQ + a broker) would remove those limits,
but is new infrastructure this project has deliberately avoided
elsewhere (ADR-0002, ADR-0007) — a first pass (matching ADR-0010's own
framing) that fixes the actual problem — the client no longer waits —
without over-building for this project's scale.

## Decision

### 1. Split `ingest_document()` into two phases
`ingest_document()` is called directly, synchronously, by every test
and eval across Phases 9-13 — none of that can break. So the split
keeps `ingest_document()` itself as a thin, byte-for-byte-unchanged
synchronous wrapper:

- `create_pending_knowledge_doc(db, title, source, content)` — fast:
  just the `KnowledgeDoc` row (full `content` stored immediately, a
  single INSERT), status `PROCESSING`.
- `process_knowledge_doc(db, doc_id, ..., completed_status=PENDING_REVIEW)`
  — the existing chunk/contextualize/embed/persist-`DocChunk` logic,
  essentially unchanged, wrapped in a try/except so a chunking or
  embedding failure lands the doc in `FAILED` instead of leaving it
  stuck at `PROCESSING` forever.
- `ingest_document(...)` calls both in sequence and returns — but
  passes `completed_status=APPROVED`, not the default `PENDING_REVIEW`
  (see the note on trust below).

**`ingest_document()` marks the doc `APPROVED` directly, skipping the
review queue.** It's the trusted, direct-call path used by seed
scripts and every eval in this codebase — not the staff-facing HTTP
upload path (`POST /knowledge`) the review gate exists for. Making it
default to `PENDING_REVIEW` instead would have silently broken every
retrieval eval from Phases 9-13 (their ingested docs would no longer
be searchable) for a trust boundary those callers don't actually cross
— they're not "documents arriving from a less-controlled source," the
threat this ADR's review gate targets.

### 2. `POST /knowledge` uses the split, backgrounding the slow half
Calls `create_pending_knowledge_doc()` synchronously (fast, returns
201 immediately with the doc in `PROCESSING`), then
`background_tasks.add_task(...)` schedules `process_knowledge_doc()`.

The background callback needs its own DB session — the request's
session is unsafe to reuse once the response cycle ends. Rather than
hardcoding `app.database.SessionLocal` at the call site, the router
takes it via a new dependency, `get_session_factory()` (`app/database.py`),
and passes the resolved factory into the background task. This exists
specifically so tests can override it — see Consequences below for why
that turned out to matter more than expected.

### 3. Source review workflow (closes threat-model item #8)
- `KnowledgeDocStatus` (`app/models/knowledge.py`): `PROCESSING`,
  `PENDING_REVIEW`, `APPROVED`, `REJECTED`, `FAILED`. Postgres enum
  labels are uppercase, matching the Python member `.name` (ADR-0010's
  casing lesson).
- Migration `f54e84a5c89a` adds `knowledge_docs.status`, backfilling
  every existing row to `APPROVED` via a `server_default` that's
  dropped immediately after (already-trusted content shouldn't vanish
  from search; the model's own Python-side default, also `APPROVED`,
  covers ordinary ORM inserts going forward — dropping the DB-level
  default just stops it from silently masking a raw-SQL insert that
  forgot to set `status`).
- `POST /knowledge/{id}/approve` and `POST /knowledge/{id}/reject`,
  admin-only (`require_role(UserRole.ADMIN.value)` — stricter than
  `STAFF_ROLES`; reviewing what an agent submitted is a distinct
  permission from submitting it). Both return 409 if the doc isn't
  currently `PENDING_REVIEW`.
- `retrieve_relevant_chunks()` filters both the vector and keyword
  queries to `KnowledgeDoc.status == APPROVED` — the actual enforcement
  point. A `PROCESSING`/`PENDING_REVIEW`/`REJECTED`/`FAILED` doc is
  invisible to `/knowledge/search` and the triage pipeline.
  `GET /knowledge` (the staff list) stays unfiltered — staff need to
  see and manage everything, including failed/pending items.
- `KnowledgeBasePage.tsx` gets a status badge per doc and admin-gated
  Approve/Reject buttons on `pending_review` docs — without this,
  admins have no practical way to exercise the control.

## Alternatives considered
- **A real task queue (Celery/arq/RQ)** — removes `BackgroundTasks`'
  durability/retry gaps entirely, but is new infrastructure (a broker,
  a worker process) this project has consistently avoided for a
  problem `BackgroundTasks` already solves at this scale. Revisit if
  ingestion volume or reliability requirements actually demand it.
- **A fixed `max_length` cap on document content** — tried first,
  rejected (see Context). Left no trace in the schema; `KnowledgeDocCreate.content`
  has no `max_length`.
- **Making `ingest_document()` default to `PENDING_REVIEW` like the
  HTTP path** — rejected: it conflates "content arriving through a
  less-controlled channel" (the actual threat) with "content this
  codebase's own test/eval suite ingests directly," and would have
  required touching every Phase 9-13 eval to route around a review gate
  they have no reason to be subject to.

## Consequences
- **A real process lesson about testing `BackgroundTasks`, worth
  recording plainly.** `TestClient` runs the whole ASGI cycle —
  including background tasks — to completion before `client.post()`
  returns, but the JSON response body is serialized from the route
  handler's return value *before* the background task runs, not after.
  So `response.json()["status"]` is always `"processing"` even though,
  by the time control returns to the test, the DB row has already
  moved on to `"pending_review"`. A first draft of the ingestion test
  asserted the wrong one and failed immediately — fixed by asserting
  the response body reflects the pre-background state and querying the
  DB directly for the post-background state.
- **A second, more consequential testing gap, caught before it shipped
  a real regression risk rather than after:** hardcoding
  `app.database.SessionLocal` inside the background callback (the
  obvious first implementation) would have opened a session against
  the *real* dev-database engine from inside every integration test
  that hits `POST /knowledge` — silently writing to `support_platform`
  instead of the isolated `support_platform_test` database, exactly
  the pollution bug ADR-0016 already hit twice and had to clean up by
  hand. The `get_session_factory()` dependency exists specifically so
  `tests/integration/conftest.py` can override it the same way it
  already overrides `get_db` — returning the shared, transactional
  `db_session` fixture instead, so background-task writes roll back
  with everything else at teardown.
- `KnowledgeDocCreate.content` still has no `max_length` — unbounded
  documents remain possible by design; background processing is the
  actual mitigation for the latency risk that would otherwise imply,
  not a cap.
- No API contract break: `ingest_document()`'s signature and behavior
  are unchanged for every existing caller; only `POST /knowledge`'s
  response now includes `status`, and newly-ingested docs via that
  route aren't searchable until an admin approves them (a real,
  intentional behavior change for that one path — the point of this
  ADR).
