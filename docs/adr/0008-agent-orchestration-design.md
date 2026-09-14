# ADR-0008: Agent orchestration design

**Status:** Accepted
**Date:** 2026-09-14

## Context
`agent_decisions`, `retrievals`, and `guardrail_checks` (ADR-0004) have
existed since phase 1 with no code ever writing to them. RAG retrieval
(ADR-0007) is a standalone endpoint nothing calls. `app/guardrails/
injection.py` runs in no request path. And `tests/evals/
test_classification_eval.py` has been `@pytest.mark.skip`'d since the
project's initial scaffold, already committed to a specific contract:
`app.agent.classify.classify_ticket(text) -> label`. This phase wires
all of these together into one real pipeline and finally exercises the
schema they were built for.

## Decision
1. **Trigger: manual `POST /tickets/{id}/triage`, not automatic on
   ticket creation.** Keeps `POST /tickets` fast and free of model
   calls; avoids the "unthrottled endpoint calling Claude" cost risk
   `project-brief.md` already names as a real production concern.
2. **Pipeline order:**
   `injection check (raw text)` → if caught, `escalate` immediately
   with **no further model calls** (cost + safety) → `PII redaction` →
   `RAG retrieval` (existing `retrieve_relevant_chunks`) → `Ollama
   classification` (informational category label) → `routing decision
   from the top retrieval's similarity score` → `Claude draft
   generation` if the decision is `draft_for_review`/`auto_respond`.
3. **Routing decision comes from retrieval similarity, not a second
   Ollama call.** A 1B local model reliably emitting a calibrated
   numeric confidence score is fragile; pgvector already returns a real
   cosine-similarity float per retrieved chunk (ADR-0007). Thresholds
   (explicitly starting guesses, same as `ai-architecture.md` already
   admits for this number): `< 0.5` → `escalate`, `0.5–0.8` →
   `draft_for_review`, `≥ 0.8` → `auto_respond`. The threshold check
   itself is logged as a `guardrail_checks` row
   (`stage=output, check_type=confidence_threshold`).
4. **Ollama classification is separate from routing.**
   `app/agent/classify.py::classify_ticket` categorizes the ticket
   (`billing`/`bug`/`account`/`feature_request`, matching the existing
   `golden_set.jsonl`) purely for the classification eval and for
   `agent_decisions.reasoning` — it does not affect `auto_respond`/
   `draft_for_review`/`escalate` routing.
5. **`model_used` is comma-separated when more than one model
   contributed to a decision** — e.g.
   `"ollama/llama3.2:1b,claude-haiku-4-5-20251001"` for a drafted reply,
   or just `"ollama/llama3.2:1b"` for a decision made from
   classification/retrieval alone with no draft. This is a pragmatic
   fit to the existing single-string column (ADR-0004), not a schema
   change — a real limitation if per-model-call cost/latency tracking
   is ever needed at finer granularity than "which models touched this
   decision."
6. **Tool call beyond retrieval: `get_account_context`** — requester's
   account age and prior ticket count, both already in the schema.
   Folded into the Claude prompt and into `reasoning`, but does not
   change the routing math. Deliberately not a fabricated SLA/billing
   lookup — there's no such data model yet, and inventing one just to
   have a "tool call" would be dishonest scaffolding.
7. **PII redaction ships now, not in a later phase.** `app/guardrails/
   pii.py::redact_pii` — same deliberately-simple, pattern-based style
   as `injection.py` (regex for emails, phone numbers, credit-card-like
   digit runs), swappable for a classifier later. Redacted text — never
   raw ticket text — is what reaches classification, retrieval query
   embedding, and the Claude prompt. `docs/threat-model.md` threat #2
   moves from "Planned" to "Implemented (pattern-based)."
8. **Output-guardrail scope stays narrow this phase.** Only
   `confidence_threshold` is checked. Schema validation of Claude's
   output and an LLM-judge groundedness score are phase 6's job per
   `project-brief.md`'s sequence — not pulled forward, not silently
   dropped either.
9. **Ollama model: `llama3.2:1b`.** Chosen once disk headroom (~20GB
   free, vs. ~3GB during the two earlier failed pulls) actually made
   running Ollama feasible; a well-known, small, "good enough for ticket
   classification" model.

## Alternatives considered
- **Fully automatic triage on ticket creation** — closer to a literal
  reading of "agentic triage," but couples every ticket write to model
  latency/cost with no throttle. Rejected for this phase; revisit once
  rate limiting (already a project-brief open item) exists.
- **A second Ollama call for confidence scoring** — more symmetric with
  "Ollama does the routine work," but small local models are unreliable
  at emitting calibrated numeric scores in a fixed format. Retrieval
  similarity is a real number already available for free.
- **A fabricated SLA/billing tool call** — would look more like a
  "real" support platform, but there's no underlying data to back it;
  using real (if modest) account data is more honest than inventing a
  subsystem.

## Consequences
- `agent_decisions`, `retrievals`, and `guardrail_checks` finally have
  real rows — the Ollama-vs-Claude cost/latency comparison
  (`project-brief.md` open item) now has data to compute from.
- The 0.5/0.8 similarity thresholds are guesses; `tests/evals/
  test_triage_eval.py` is the mechanism for revisiting them with real
  accuracy numbers instead of intuition.
- `model_used`'s comma-separated convention means any future
  per-model-call cost breakdown needs either string-parsing or a schema
  change — documented now so it isn't a surprise later.
- Output-side guardrails (schema validation, groundedness) are known,
  intentionally-deferred gaps until phase 6, not silently missing
  gaps discovered later.
