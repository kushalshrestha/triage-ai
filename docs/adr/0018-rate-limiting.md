# ADR-0018: Rate limiting on AI-facing endpoints

**Status:** Accepted
**Date:** 2026-09-21

## Context
`docs/threat-model.md` item #4 (Denial of service / cost abuse):
"Unbounded requests to the AI endpoints run up LLM API cost" —
mitigation "Rate limiting on AI-facing endpoints," status "Planned."
`project-brief.md`'s review notes call it out directly: "worth adding
once the model router exists — both a cost-control story and a
legitimate platform-engineering concern (an unthrottled endpoint
calling Claude is a real production risk)." The model router has
existed since Phase 7 (ADR-0010); this closes the gap.

Three endpoints actually invoke a model and are reachable by any
authenticated user:
- `POST /tickets/{id}/triage` — Ollama classification + groundedness
  judge, and Claude drafting once retrieval clears the draft
  threshold. The real cost driver.
- `POST /knowledge` — local embedding compute (backgrounded as of
  ADR-0017), staff-only but still unbounded.
- `GET /knowledge/search` — local embedding compute, reachable by
  **any** authenticated user including customers — the widest-open of
  the three.

## Decision

### Mechanism: hand-rolled in-memory fixed-window limiter, no new infra
Checked `docker-compose.yml` before choosing this: the `api` service
runs a single `uvicorn` process — no `--workers`, no replicas — so a
module-level in-memory counter is genuinely process-wide state for
this deployment, not an approximation glossed over. This follows the
project's established pattern of not reaching for new infrastructure
until scale actually demands it (ADR-0002 pgvector-in-Postgres,
ADR-0007 avoiding extra services, ADR-0017's `BackgroundTasks` over a
task queue). A Redis-backed limiter (`slowapi`/`limits`) would remove
the single-process caveat, at the cost of a new service this project's
scale doesn't yet justify — revisit if it's ever deployed with
multiple replicas.

### `app/rate_limit.py`
- `check_rate_limit(key, max_requests, window_seconds, *, now)` — a
  pure function (fixed-window counter, `dict[str, (window_start, count)]`),
  taking `now` explicitly rather than calling `time.monotonic()`
  internally so unit tests can drive it with a fake clock
  deterministically. Same "pure function, thin wrapper" split already
  used in `app/agent/ollama_client.py` (`generate_raw`/`generate`).
- `rate_limit(key, max_requests, window_seconds)` — the FastAPI
  dependency factory, matching the shape of `app/dependencies.py`'s
  `require_role(*roles)`. Keyed per authenticated user
  (`f"{key}:{current_user.id}"`), not IP — every protected endpoint
  already requires auth, and per-user avoids the usual per-IP problems
  (shared NAT, proxies).
- Defined `async def` on purpose. FastAPI runs a plain `def`
  dependency in a threadpool; two concurrent requests from the same
  user could then race on the shared dict's read-modify-write. An
  `async def` with no `await` inside instead runs on the single-
  threaded event loop, making the check-and-increment atomic without
  an explicit lock.
- Raises `HTTPException(429, ..., headers={"Retry-After": ...})` when
  exceeded.

### Config (`app/config.py`)
```python
triage_rate_limit_per_minute: int = 5
knowledge_ingest_rate_limit_per_minute: int = 20
knowledge_search_rate_limit_per_minute: int = 30
```
One 60-second window for all three, kept deliberately simple (one
knob per endpoint). Triage is tightest since it's the one that can
spend real Claude money; search is loosest since it's read-only and
the cheapest model call (local embedding only).

### Wiring
Added to each endpoint's existing `Depends(...)` list, same style as
`require_role`: `app/routers/agent.py::trigger_triage`,
`app/routers/knowledge.py::create_knowledge_doc` and `::search_knowledge`.
`DELETE /knowledge/{id}`, `/approve`, `/reject`, and ticket CRUD are
out of scope — none of them call a model, so they're not what
threat-model item #4 is about.

## Real measured behavior
Verified against the running API, not just the test suite: hit
`POST /tickets/{id}/triage` 6 times rapidly as one agent user. The
first 5 returned 201; the 6th returned 429 with `Retry-After: 22`.
A second agent user, same window, was unaffected — confirming the
per-user keying.

## Alternatives considered
- **A real distributed limiter (Redis + `slowapi`/`limits`)** — the
  correct choice once this runs behind more than one process/replica;
  not justified yet for a single-container deployment, and would be a
  new piece of infrastructure this project has consistently avoided
  until the scale need is real.
- **Per-IP keying** — rejected: every target endpoint already requires
  auth, so per-user is strictly more precise (no shared-NAT
  false-positives, no trivial IP-rotation bypass) at no extra cost.
- **A single limit shared string across endpoints instead of one per
  endpoint type** — rejected: triage is the one endpoint that spends
  real money, and deserves a meaningfully tighter limit than free
  local-embedding endpoints; collapsing them into one number would
  either over-restrict search or under-protect triage.

## Consequences
- No schema change — the limiter's state is entirely in-process
  memory, never persisted.
- **Known, accepted limitation, stated plainly rather than hidden**:
  state resets on process restart, and isn't shared across multiple
  workers/replicas — correct for this project's actual single-process
  deployment today, wrong the moment it's ever scaled horizontally
  without also moving to a shared store.
- `rate_limit(...)` is evaluated once, at router-import time (the same
  as `require_role(*roles)`), so limit values are fixed for the
  process's lifetime — a `Settings` change requires a restart to take
  effect, same as every other `get_settings()`-derived value baked
  into a route signature. This also means tests can't override the
  configured limit per-test; the new rate-limit tests instead loop the
  real configured default the right number of times.
- Every existing test that exercises these three endpoints was
  checked against the new limits before shipping (at most 1-2 calls
  per distinct per-test user, well under 5/20/30) — none needed
  changes; the retrieval evals (Phases 9-13) bypass the HTTP layer
  entirely, so they're unaffected by construction.
