# ADR-0028: Resilience to model-call failures, not just bad output

**Status:** Accepted
**Date:** 2026-10-05

## Context
Auditing Output guardrails ("confidence-based escalation") surfaced a
gap spanning all three model-call sites in the triage pipeline: each
already handled its model returning *bad output* (unparseable text, a
malformed tool call) but none handled the call itself *failing* —
Ollama unreachable/timed out, or the Claude API erroring/rate-limited.

Confirmed by direct code reading:
- `app/agent/classify.py::classify_ticket_with_fallback` called
  `generate()` (Ollama) with no try/except around the call itself —
  only `_match_category`'s *parsing* of the result was handled. An
  unreachable Ollama raised `httpx.HTTPError` straight through
  `run_triage()` to the FastAPI endpoint: an uncaught 500.
- `app/agent/judge.py::assess_groundedness` — same shape: an
  unreachable judge crashed the whole triage request instead of the
  system failing safe.
- `app/agent/drafting.py::generate_draft` —
  `client.messages.create()` wasn't wrapped; only the *response*
  (missing tool call, schema validation) was checked afterward. A
  Claude outage/rate-limit/auth error raised `anthropic.APIError`
  uncaught.

The irony: this project already built the right failure-handling
*philosophy* for bad output — classification's self-detecting-failure
fallback (ADR-0023), and the judge's existing fail-safe default to
"not grounded" on an empty response (`judge.py::_parse_verdict`) — it
just never extended that philosophy to the call failing outright. A
transient Ollama hiccup caused a *worse* outcome (unhandled 500) than
a bad answer did (safe escalation/fallback) — backwards for a
guardrail whose entire job is failing safe.

## Decision
Catch each failure at the call site that already knows the right safe
default for its own use case, not inside the shared
`app/agent/ollama_client.py::generate`, which stays a clean,
policy-free primitive reused by both callers with different needs.

- **`classify.py`**: the initial Ollama call in
  `classify_ticket_with_fallback` is now wrapped in
  `try/except httpx.HTTPError`, treating a failed call exactly like an
  unparseable one — falls through to the existing, already-tested
  Claude-fallback block.
- **`judge.py`**: `generate()` in `assess_groundedness` is wrapped in
  `try/except httpx.HTTPError`, returning
  `(False, "groundedness check failed: {exc}")` — the same fail-safe
  philosophy already used for an empty response, extended to an
  unreachable judge.
- **`drafting.py`**: `client.messages.create()` is wrapped in
  `try/except anthropic.APIError`, re-raised as the existing
  `DraftSchemaError` (no `usage` available since the call never
  completed — already handled, defaults to `None`).

**No `orchestrator.py` changes were needed.** It already treats
`groundedness_passed=False` as "downgrade auto_respond" and already
catches `DraftSchemaError` to force `ESCALATE` — both are provably the
same code paths `test_ungrounded_draft_downgrades_auto_respond_to_draft_for_review`
and `test_malformed_draft_escalates_instead_of_surfacing_a_broken_reply`
already exercise. Translating a call failure into the same shape as a
bad-output failure, at the source, was the entire fix — the downstream
"fail safe" behavior already existed and just needed to actually be
reached.

## Alternatives considered
- **Catch broadly (`except Exception`) at each site** — rejected:
  too broad, would mask real bugs (e.g. a `TypeError` from a code
  defect) as if they were a transient infra failure. `httpx.HTTPError`
  and `anthropic.APIError` are the precise exception hierarchies for
  "the call itself failed," not "the code is broken."
- **Catch inside `ollama_client.py::generate`** — rejected: the two
  callers want different safe defaults (classify.py wants to fall back
  to Claude; judge.py wants to fail toward "not grounded"). Catching
  in the shared primitive would force one policy on both, or require
  a parameter to choose — more complexity than catching at each
  call site, which already knows its own right answer.
- **A circuit breaker / retry layer** — considered and rejected as
  premature: this project's volume doesn't justify the added
  infrastructure yet; fail-safe-on-first-failure is the right scope
  for now, same reasoning ADR-0017 applied to deferring a real task
  queue for ingestion.

## Consequences
- No schema change, no new `GuardrailCheckType` — `GuardrailCheck`
  rows for `PII_REDACTION`/`GROUNDEDNESS`/`SCHEMA_VALIDATION` already
  record whatever `passed`/`details` the (now more resilient)
  functions return; nothing new needs persisting.
- New unit tests are the real regression coverage here, not new
  integration tests: `test_classify.py::test_fallback_calls_claude_when_ollama_is_unreachable`,
  `test_judge.py` (new file — `judge.py` had no unit tests before this,
  only the real-model eval), and
  `test_drafting.py::test_api_connection_failure_raises_draft_schema_error`
  each confirm the *translation* from call failure to safe return
  value/exception. The orchestrator-level behavior for those safe
  values was already proven by existing integration tests — adding new
  ones would have just re-tested the same already-covered paths.
- `app/agent/ollama_client.py`'s `timeout=60.0` means a genuinely stuck
  Ollama still adds real latency before failing safe — this fix stops
  the crash, it doesn't make the failure instant. Not addressed here;
  a shorter timeout tuned from real latency data is a separate,
  measured decision for later if this ever matters in practice.
