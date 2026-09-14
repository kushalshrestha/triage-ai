# ADR-0009: Output-side guardrails — schema validation and groundedness

**Status:** Accepted
**Date:** 2026-09-14

## Context
ADR-0008 deliberately scoped phase 5 to only the `confidence_threshold`
output check, deferring schema validation and a groundedness
(hallucination) check to this phase. `Claude`'s draft currently comes
back as an unvalidated free-text string with nothing checking it's
well-formed or actually grounded in what was retrieved.
`guardrail_checks.check_type` has had `SCHEMA_VALIDATION` and
`GROUNDEDNESS` enum values sitting unused since ADR-0004.

## Decision
1. **Schema validation via forced tool-use.** `generate_draft`
   (`app/agent/drafting.py`) forces Claude to respond through a
   `submit_draft` tool call (`tool_choice={"type": "tool", "name":
   "submit_draft"}`) with a fixed JSON schema: `reply_text` (string)
   and `cited_chunk_indices` (which of the provided context chunks the
   reply draws from). The result is Pydantic-validated (`DraftOutput`).
   A structural failure — a malformed tool call, or a cited index
   outside the chunks actually provided — fails the `schema_validation`
   guardrail check and the ticket **escalates outright**. A malformed
   draft never reaches a human framed as something reviewable.
2. **Groundedness via a second, independent Ollama call.**
   `app/agent/judge.py::assess_groundedness(reply_text, context_chunks)
   -> (bool, str)`, same deterministic-temperature style as
   `classify.py`. Chosen over a second Claude call (would compound the
   per-decision cost `project-brief.md` already flags as a concern) and
   over a lexical-overlap heuristic (too coarse to catch a fluent but
   unsupported claim). Matches the project's existing "Ollama for
   routine/local work, Claude for the one thing that's worth paying
   for" split.
3. **A failed groundedness verdict downgrades the decision, not just
   logs it.** If the judge says "ungrounded": `auto_respond` downgrades
   to `draft_for_review` (an unreviewed, possibly-hallucinated reply
   must never auto-resolve a ticket), and `ticket.status` follows the
   downgraded decision. `draft_for_review` stays `draft_for_review` —
   it was already headed to a human. This is the actual enforcement
   point; the guardrail row alone would just be an audit log.
4. **`model_used` dedupes.** Groundedness reuses Ollama (already listed
   for classification), so the comma-separated convention from
   ADR-0008 now needs to not list the same model twice per decision.

## Alternatives considered
- **A second Claude call as the judge** — plausibly higher-quality
  judgments, but doubles the paid-API cost of every drafted decision.
  Rejected for the same reason ADR-0008 avoided a second Ollama call for
  routing: cost discipline over marginal quality here.
- **A lexical/keyword-overlap heuristic instead of an LLM judge** —
  free and instant, but blind to fluent hallucination (a reply can
  reuse plenty of the context's vocabulary while still asserting
  something the context never said). Rejected as too weak a check to
  be worth calling a guardrail.
- **Log the groundedness score without downgrading the decision** —
  simpler, but makes the guardrail purely observational instead of a
  real safety mechanism. Rejected — `auto_respond` with no human in the
  loop is exactly the case this guardrail exists to catch.

## Consequences
- Every drafted decision now costs one extra local Ollama call
  (groundedness) on top of the existing classification call — free and
  local, but real added latency per triage request.
- **A real prompt-engineering finding while building this**:
  `llama3.2:1b` initially misjudged a clearly-grounded, accurately
  paraphrased reply as "ungrounded" — even after adding explicit
  "paraphrasing still counts as grounded" instructions and two
  few-shot examples to `judge.py`'s prompt. The fix that actually
  worked was the opposite of "add more guidance": a short, direct
  yes/no question ("Does the reply only use information present in the
  context, without adding new facts?") outperformed the longer,
  more-explained version. Small local models can get *worse* with more
  prompt scaffolding, not better — worth remembering before reaching
  for a longer prompt as the default fix next time.
- **A real infrastructure finding, also from building this**: even at
  `temperature: 0`, two different judge calls run shortly after each
  other sometimes returned the *same* verdict regardless of their
  actual (different) content — a warm Ollama model appears to carry
  cached state across nominally-independent `/api/generate` requests.
  It reproduced with `OLLAMA_NUM_PARALLEL=1` set (so it isn't purely a
  concurrent-request-slot issue) and survived changing prompt structure
  and adding a random per-request nonce (so it isn't literal
  string-prefix matching either). The fix that reliably worked:
  `keep_alive: 0` on every Ollama call (`app/agent/ollama_client.py`),
  forcing a full model unload/reload each time — confirmed stable
  across repeated runs after nothing short of that was. Real cost:
  ~5–6s reload latency per Ollama call instead of ~0.5s warm, on top of
  `docker-compose.yml` now also setting `OLLAMA_NUM_PARALLEL=1` for the
  `ollama` service as defense in depth. Acceptable here — triage is a
  manually-triggered, not-latency-critical action — but it's a real
  tradeoff, and the root cause inside Ollama's serving layer is still
  not fully understood, just reliably worked around.
- `project-brief.md`'s review notes already flag that judge models need
  their own reliability sanity-check before being trusted for gating.
  `tests/evals/test_groundedness_eval.py` is a first, small data point
  (two hand-crafted examples), not the full "run the judge twice on 10
  examples, confirm stability" study that note calls for — tracked as
  an open question in `ai-architecture.md`, not silently skipped.
- `cited_chunk_indices` is currently informational (stored on the
  `TicketEvent` payload) beyond the out-of-range structural check —
  nothing yet cross-references it against the groundedness verdict
  itself. A tighter future version could require every claim in
  `reply_text` to trace to a cited chunk specifically, not just "some
  chunks were cited and they're valid indices."
