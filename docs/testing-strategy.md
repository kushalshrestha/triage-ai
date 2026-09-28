# Testing strategy

Traditional unit tests assert exact output. Most of this codebase is
still tested that way — but model calls can't be, because the same
prompt can return different wording on different runs. Testing
therefore splits into layers:

## 1. Unit tests — `tests/unit/`
Deterministic code: guardrail rules, PII redaction, schema validators,
routing logic, prompt template rendering. Exact-match assertions, same
as any backend code. Example: `tests/unit/test_guardrails.py`.

## 2. Integration tests — `tests/integration/`
Real API endpoints against a real (test) DB. The LLM call is mocked
with a fixed stub response so these stay fast and non-flaky. Verifies
plumbing — persistence, status codes, routing — not model quality.
Example: `tests/integration/test_tickets_api.py`.

## 3. Eval tests — `tests/evals/`
The AI-specific layer. Assert against a **threshold over a fixed
dataset**, not exact output: classification accuracy ≥ 0.90, RAG
faithfulness ≥ 0.8, LLM-as-judge quality ≥ 4/5. A small smoke subset
runs on every PR; the full golden set runs nightly or pre-release.
Example: `tests/evals/test_classification_eval.py`.

## 4. Adversarial / safety tests — `tests/evals/test_safety_eval.py`
Unlike (3), these ARE deterministic pass/fail — testing the guardrail
layer around the model, not the model's free-form output. Either the
injection attempt got caught or it didn't. Grow this set whenever a
new attack pattern is found.

## 5. Regression gating (CI)
Golden-set scores get snapshotted per prompt/model version
(`tests/evals/regression_baseline.json`, ADR-0024) — a committed file,
not a live database query: `eval_runs` doesn't persist across CI runs
(each workflow gets a fresh, ephemeral Postgres), so a snapshot file is
the only thing that actually survives to compare against. A PR that
drops an eval score more than a small tolerance below the committed
baseline is blocked — deliberately a *tolerance*, not zero, since real
cross-architecture inference variance (ADR-0020, ADR-0022) can move a
score by itself with no prompt change at all. Updating the baseline is
a deliberate, human action taken in the same change as an intentional
prompt/model update, the same way snapshot-testing tools work
elsewhere in the industry — never auto-ratcheted by CI itself. Wired
into `test_classification_eval.py` and `test_groundedness_eval.py` so
far — the two evals with real prompt-variant experiment history
(ADR-0020, ADR-0022) — not every eval; retrieval and triage-routing
are threshold/algorithm-driven, not prompt-driven, so this doesn't
apply to them the same way.

## 6. Load/latency tests
p95 latency and cost per ticket type, measured separately from
correctness, split by Ollama vs. Claude routing.

## What NOT to do
Don't try to unit-test raw model output with exact-match assertions —
it will be flaky by construction and teaches the wrong lesson about
how these systems are actually validated. If you're writing
`assert response == "exact string"` against a live model call, that
assertion belongs in an eval test with a threshold, or the call
should be mocked.
