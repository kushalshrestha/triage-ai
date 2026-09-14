# ADR-0010: LLMOps first pass — cost/latency capture, prompt versioning, CI eval gate

**Status:** Accepted
**Date:** 2026-09-15

## Context
Phases 1–6 are done. `system-architecture.md`'s "Observability layer"
promises "every model call is logged with latency, token cost," but no
column anywhere captures either — `agent_decisions` only has
`confidence_score`/`model_used`/`reasoning`. This blocks the actual
premise the README leads with: routing "backed by measured cost and
latency, not preference." There's nothing to measure yet.

Separately, `.github/workflows/ci.yml` already exists (a stale
`project-brief.md` review note claims it doesn't) with a `lint-and-scan`,
`test`, and `eval-smoke` job. `eval-smoke` runs the entire eval suite
with `continue-on-error: true` and a comment saying "non-blocking until
phase 4 lands" — stale now that phase 5 built `classify_ticket` and
every eval test genuinely passes. It also has no Ollama service, so it
can't run the Ollama-calling evals in CI at all today.

## Decision
1. **`agent_decisions` gets three new nullable columns**:
   `total_latency_ms`, `claude_input_tokens`, `claude_output_tokens`.
   Considered a dedicated `model_calls` table again (ADR-0004 already
   rejected this once); rejected again for the same reason — Claude
   usage is a property of the one drafting call inside a decision, not
   a new decision-shaped concept, and `agent_decisions.model_used`
   already established the "one row can summarize more than one model
   call" pattern (ADR-0008).
2. **`EvalRunType` gains `RETRIEVAL` and `ROUTING`.** Populating
   `eval_runs` for real surfaced that its original 4 values
   (`classification`/`faithfulness`/`judge`/`safety`) don't cover two
   evals already shipped: `test_retrieval_eval.py`'s recall@k (not a
   generation-faithfulness question) and `test_triage_eval.py`'s
   auto_respond/draft/escalate routing accuracy. `faithfulness` maps
   cleanly to `test_groundedness_eval.py` (`ai-architecture.md`
   already describes faithfulness as "whether a response is actually
   grounded in what was retrieved" — that's groundedness exactly).
   `judge` stays unused for now — reserved for a general draft-quality
   LLM-judge score, which doesn't exist yet.
3. **Prompt versioning is a version constant per prompt**
   (`app/agent/classify.py`, `drafting.py`, `judge.py`), recorded on
   `eval_runs.prompt_version` — the column that's existed for exactly
   this since ADR-0004. Not added to `agent_decisions`, which has no
   such column and doesn't need one yet with one version per prompt.
4. **`eval_runs` gets populated via a separate, real (non-rollback)
   session**, not the existing `db_session` fixture
   (`tests/conftest.py`). That fixture's writes are deliberately never
   persisted — correct for test isolation, wrong for a historical eval
   log. `tests/evals/conftest.py` adds a session bound to the real dev
   database just for this; `db_session` keeps seeding each eval's
   throwaway test data as before.
5. **CI regression gating is the existing hardcoded per-test
   thresholds, not a new baseline-snapshot file.**
   `testing-strategy.md` layer 5 describes snapshotting scores per
   prompt version for regression comparison — the appropriately-sized
   version of that today, with one version per prompt and no history
   to snapshot against, is: the threshold in each eval test already is
   the baseline, and CI actually enforcing it (removing
   `continue-on-error`) already is the gate. A file-based snapshot
   system before there's a second prompt version to compare against
   would be built for a problem that doesn't exist yet.
6. **Smoke vs. full CI split is by real $ cost, not just speed.** A new
   `@pytest.mark.costly` marks `test_triage_eval.py` specifically — the
   only eval test that calls Claude. Everything else (`test_safety_eval`
   — no model call; `test_classification_eval`, `test_groundedness_eval`
   — Ollama only, free; `test_retrieval_eval` — local embeddings only,
   free) runs on every PR via a now-blocking `eval-smoke` job with a
   real `ollama` service container and a model-pull step. A new
   `eval-full` job runs everything nightly (`schedule:` cron) plus
   `workflow_dispatch:` for a manual run, and needs the
   `ANTHROPIC_API_KEY` repo secret set — flagged here since that's a
   GitHub repo setting I can't configure myself.

## Alternatives considered
- **A `model_calls` log table** — more granular (every call, not just
  decision-level aggregates), but reopens the exact tradeoff ADR-0004
  already made a call on. Rejected for consistency.
- **A committed baseline-scores file for CI regression gating** — the
  "more correct" long-term design per `testing-strategy.md`, but real
  over-engineering before a second prompt version exists to regress
  against. Revisit when prompt iteration actually starts happening.
- **Full Langfuse/tracing integration this pass** — the project-brief
  tech-stack line item this whole ADR is partially in service of, but a
  genuinely bigger lift (new service, new integration surface) than a
  "first pass" should absorb. Deferred, tracked as an open question in
  `ai-architecture.md` rather than silently dropped.

## Consequences
- `scripts/cost_report.py` is the practical, buildable version of
  project-brief.md's "cost/latency comparison" interview artifact for
  now — a report generator over real columns, not a live dashboard.
  Revisit once there's enough decision volume for the report to say
  something interesting.
- CI eval spend is now bounded: every PR pays for Ollama-only evals
  (free), only the nightly/manual `eval-full` run pays for a real
  Claude call.
- The CI workflow changes are reviewed for YAML validity and job
  structure here, not verified by an actual GitHub Actions run (no
  `act` or equivalent available in this environment) — real
  verification happens on the next push/PR.
