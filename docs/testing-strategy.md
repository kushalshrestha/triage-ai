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
Golden-set scores get snapshotted per prompt/model version. A PR that
drops eval scores below the last known-good baseline is blocked. This
is the LLMOps tie-in: prompt versioning + eval gate becomes the CI
check, not a separate process.

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
