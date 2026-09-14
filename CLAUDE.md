# TriageAI — project instructions

AI-native support ticketing platform. Full design context:
@README.md @docs/system-architecture.md @docs/ai-architecture.md
@docs/testing-strategy.md @project-brief.md

## Commands
- Run everything: `docker compose up`
- All tests: `docker compose exec api pytest`
- Unit only (fast, deterministic): `docker compose exec api pytest tests/unit`
- Integration: `docker compose exec api pytest tests/integration`
- Evals (slow, calls real models): `docker compose exec api pytest tests/evals`
- New migration: `docker compose exec api alembic revision --autogenerate -m "<message>"`
- Apply migrations: `docker compose exec api alembic upgrade head`

## Hard rules
- Every non-trivial architecture or AI-system decision gets an ADR in
  `docs/adr/` (use `docs/adr/template.md`), written before or alongside
  the code — not reconstructed afterward.
- New guardrail or agent logic ships with tests in the matching layer
  (`tests/unit/` for deterministic code, `tests/evals/` for model-facing
  behavior) in the same change. No code without a test in the same PR.
- Never write an exact-match assertion against a live model call.
  Model output belongs in `tests/evals/` with a threshold, not
  `tests/unit/` with `==`.
- Extend `tests/evals/golden_set.jsonl` and `tests/evals/test_safety_eval.py`
  whenever a new ticket category or attack pattern comes up. These are
  living regression suites, not one-time fixtures.
- `agent_decisions.model_used` must be logged on every model call — it's
  the only source of truth for the Ollama-vs-Claude comparison in
  `docs/ai-architecture.md`.
- All local dev runs through `docker compose`. No ad hoc local venv
  installs or running the API outside a container.

## Layout
- `backend/app/` — FastAPI app: `routers/`, `models/`, `guardrails/`, `agent/`
- `backend/tests/` — `unit/`, `integration/`, `evals/` (see testing-strategy.md
  for what belongs where and why)
- `docs/adr/` — one file per architecture decision
- `docs/` — system-architecture.md, ai-architecture.md, testing-strategy.md

## Workflow
For anything touching more than one file or the schema, use plan mode
(Shift+Tab) first and confirm the approach before implementation starts.

## Secure SDLC (see ADR-0003, SECURITY.md, docs/threat-model.md)
- Work on a feature branch, never commit directly to `main`. Open a PR
  even for solo review — the CI run and PR description are the point.
- Before proposing a commit, run: `ruff check .`, `bandit -c pyproject.toml
  -r app/`, and the relevant test layer. Don't rely on CI to catch what a
  local check would have caught first.
- Any endpoint touching ticket data must include an authz check (ticket
  belongs to the requesting user) — see threat-model.md item #3. Flag it
  explicitly if a new endpoint is missing one rather than assuming it's
  handled elsewhere.
- Any new external call (a new API, a new ingestion source) gets a row
  added to `docs/threat-model.md`, not just implemented silently.
- Never run `git commit` or `git push` unless explicitly asked to in the
  prompt. Implement, verify with real command output pasted into the
  response (test runs, migration output — not just a claim that it
  worked), and stop there. Kushal reviews the diff and commits himself.
