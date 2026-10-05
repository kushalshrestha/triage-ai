# ADR-0027: PII redaction leak into the Claude drafting call

**Status:** Accepted
**Date:** 2026-10-04

## Context
Auditing "Input guardrails" (project-brief.md: "Injection detection,
PII redaction before model/log") against what's actually built. Found
a real, confirmed bug: `app/agent/orchestrator.py::run_triage` computed
`redacted_text = redact_pii(raw_text)` and used it for retrieval
(`retrieve_relevant_chunks`) and classification
(`classify_ticket_with_fallback`), but `generate_draft()`
(`app/agent/drafting.py`) took the whole `Ticket` object and built its
Claude prompt directly from `ticket.subject`/`ticket.body` — raw,
unredacted. Any email, phone number, or credit-card-shaped number in a
ticket reached the real, hosted Claude API unredacted. `orchestrator.py`
still recorded a `GuardrailCheck(check_type=PII_REDACTION, passed=...)`
row per ticket, which looked like it covered this call too —
`docs/threat-model.md` item #2 claimed the mitigation was "Implemented,"
which wasn't accurate for the one call that actually leaves the system
to a third party, the most sensitive path of the three (retrieval,
classification, drafting), not a minor one.

**Why existing tests didn't catch it:** `tests/unit/test_drafting.py`
called `generate_draft()` directly with a raw `SimpleNamespace`
standing in for a `Ticket`, and only ever asserted on the parsed
`DraftOutput`/schema-error behavior — never on what was actually sent
to the mocked Claude client. `tests/integration/test_agent_triage_api.py`
mocked `orchestrator.generate_draft` wholesale, bypassing
`drafting.py`'s prompt-building code entirely, and never inspected the
mock's call arguments. No test anywhere asserted drafting receives
redacted rather than raw text — the gap was entirely untested.

**Confirmed scope** (via direct code reading, not assumed): this was
the only production leak. `classify.py`'s Claude path already receives
`redacted_text` from its caller; `judge.py` never receives raw ticket
text at all (only the model's own generated reply and retrieved
context); no logging statement or persisted `TicketEvent`/
`AgentDecision`/`GuardrailCheck` field echoes raw ticket text anywhere
in `app/`.

## Decision
Make the bug structurally impossible to repeat, not just patch the one
call site: `generate_draft()` no longer takes a `Ticket` object at all
— it takes `subject: str, body: str` directly. Removing its only
access to raw fields means the only place that can supply ticket text
to drafting is the caller, which is the only place `redact_pii` is in
scope.

- `app/agent/orchestrator.py`: redacts `ticket.subject` and
  `ticket.body` separately (same `redact_pii`, applied per-field
  instead of the combined string — `redacted_text` for
  retrieval/classification still ends up byte-identical to before,
  since neither pattern spans the subject/body newline boundary) and
  passes `redacted_subject`/`redacted_body` into `generate_draft()`.
- `app/agent/drafting.py`: signature changed to
  `generate_draft(subject: str, body: str, context_chunks, account_context)`;
  dropped the now-unused `Ticket` import entirely — there's no raw
  ticket field left in this file to leak.
- New regression tests, not just a fix: `tests/unit/test_drafting.py::test_prompt_uses_exactly_the_passed_in_subject_and_body`
  asserts the Claude client receives exactly the caller's strings
  (proving `generate_draft` does no hidden transformation either way);
  `tests/integration/test_agent_triage_api.py::test_pii_in_ticket_is_redacted_before_reaching_drafting`
  creates a real ticket with an email address in the body, triggers
  triage with the existing mocked-`generate_draft` pattern, and asserts
  the mock's captured call arguments contain `[REDACTED_EMAIL]`, not
  the raw address — the direct test this bug needed and didn't have.

## Alternatives considered
- **Just redact inside `generate_draft()` itself** — rejected: this
  would still leave `generate_draft` holding a `Ticket` (or raw
  strings) and relying on remembering to call `redact_pii` at the right
  moment, the exact failure mode that caused this bug in the first
  place. Removing the raw-field access entirely, rather than trusting
  a call to happen, is the stronger guarantee.
- **Add a test without changing the signature** — rejected: a test
  alone doesn't stop a *future* call site (e.g. a new function that
  also needs to draft something) from making the same mistake by
  passing a raw `Ticket` again. The signature change is the fix; the
  test is what proves it and guards the regression.

## Consequences
- `docs/threat-model.md` item #2 updated: this gap existed and is now
  closed, with this ADR referenced, instead of silently correcting an
  inaccurate "Implemented" with no record of it ever having been wrong.
- **Deliberately not fixed here:** `app/agent/quality.py::assess_draft_quality`
  also builds a Claude prompt from raw `ticket_subject`/`ticket_body`
  parameters. It's an evals-layer-only function (ADR-0025), never
  called from `orchestrator.py`, and its golden set
  (`draft_quality_golden_set.jsonl`) contains only synthetic content
  with no real PII — there's no real exposure today. Noted here as a
  known, accepted gap in eval infrastructure rather than silently
  ignored: if this function is ever reused against real ticket data,
  the same class of bug would need the same fix.
- No schema change, no new `GuardrailCheckType` — the existing
  `PII_REDACTION` check's logic (`redacted_text == raw_text`) was
  already correct; it just wasn't the full story of where redacted
  text actually went.
