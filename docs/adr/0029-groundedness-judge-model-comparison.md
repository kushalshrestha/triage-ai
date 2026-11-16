# ADR-0029: Groundedness judge model comparison

**Status:** Accepted
**Date:** 2026-10-06

## Context
ADR-0020 (Phase 17) measured the groundedness judge's real reliability
on `llama3.2:1b`: `consistency_rate=1.0` but `reliable_accuracy=0.636`
— a real capability ceiling, confirmed not a fixable prompt (3
rewrites all measured worse). The roadmap's deferred follow-up named
the exact next step: try a larger local model and/or Claude against
the same golden set. Scoped to Claude only (no new local model pull)
— same comparison shape as ADR-0022's classification provider
comparison.

## Decision

### 1. `app/agent/judge.py` — added a provider, same shape as `quality.py`
`GroundednessProvider = Literal["ollama", "claude"]`. The existing
Ollama logic (including ADR-0028's fail-safe `httpx.HTTPError`
handling) is unchanged, now `_assess_groundedness_ollama`. New
`_assess_groundedness_claude` uses forced tool-use with a boolean
`grounded` field (simpler than `quality.py`'s integer-enum pattern,
since this is a true binary) — schema-guaranteed valid output, same
fairness rationale as every other provider comparison in this project.
Missing/malformed tool-use returns `(False, "(no tool call)")` — the
same fail-safe-to-"not grounded" philosophy already used twice in this
file. `assess_groundedness(reply_text, context_chunks,
provider="ollama")` is the public entry point; the default is
unchanged, so every existing caller except `orchestrator.py` (see
below) is unaffected.

### 2. Real measured result — a genuine, meaningful gap
`tests/evals/test_groundedness_provider_comparison_eval.py` (new,
`@pytest.mark.costly`), same "run it twice" methodology as
`test_groundedness_eval.py`, same 11-example golden set:

| Provider | `consistency_rate` | `reliable_accuracy` |
|---|---|---|
| `ollama/llama3.2:1b` | 0.909 | **0.636** (matches ADR-0020 exactly) |
| `claude-haiku-4-5-20251001` | 1.000 | **1.000** |

Claude closes the entire gap — a real, meaningful difference, not a
tie like most comparisons in this project (hybrid search, contextual
retrieval, re-ranking).

### 3. The deciding factor: every one of Ollama's errors was the dangerous kind
Inspecting the 4 examples Ollama got wrong (`changed_specific_fact`,
`partial_hallucination`, `irrelevant_context`, `wrong_question_answered`
— all `expected_grounded: false`), Ollama's verdict was `True`
(grounded) in every single case — **100% false positives, 0% false
negatives**. For a guardrail whose entire job is gating `auto_respond`,
a false positive (saying "grounded" when it isn't) is the one
direction that actually matters: it's what would let an ungrounded
reply ship automatically. A false negative just costs an unnecessary
downgrade to `draft_for_review` — safe, merely suboptimal. This
asymmetry, not just the aggregate score, is what justified a
production change here.

### 4. Production change: `orchestrator.py` now calls groundedness with `provider="claude"`
Unlike ADR-0022's classification decision (kept Ollama as default:
informational-only, runs on 100% of triage volume), two things differ
for groundedness: it's safety-critical (gates a real customer-facing
action), and it only runs on tickets that already reached
`DRAFT_FOR_REVIEW`/`AUTO_RESPOND` and already paid for a Claude
drafting call — this is a marginal extra Claude call on an
already-Claude-touched ticket, not introducing Claude where it wasn't
present. **Scoped narrowly**: only this one call site changed.
Classification (`classify_ticket_with_fallback`, ADR-0023), the draft
quality judge (`assess_draft_quality`, default Ollama — already more
reliable than this judge, ADR-0025), and contextual retrieval
(ADR-0015) all keep their existing Ollama defaults, each independently
justified on its own measurements. `llama3.2:1b` keeps running in the
stack for all of those — this is a single-guardrail swap, not a
model-wide replacement.

Verified end-to-end, not just at the unit level: `test_triage_eval.py`
(real `run_triage()`, real Claude calls for both drafting and
groundedness) passes unchanged after the switch.

## Alternatives considered
- **Hybrid: Ollama first, Claude double-checks only a "grounded"
  verdict** — a real option, cheaper on average (skips the Claude call
  when Ollama already safely says "not grounded"), mirroring ADR-0023's
  trigger-on-risk pattern. Not chosen: more complexity for a benefit
  that's likely small in practice (most drafts probably *are*
  grounded, so Ollama would say "grounded" most of the time anyway,
  triggering the Claude check on most tickets regardless) — not
  measured directly, so stated as a reasoned judgment call, not a
  proven cost saving. Worth revisiting if real production volume ever
  shows Ollama saying "not grounded" often enough to make the skip
  meaningful.
- **No production change, document only** — considered given this
  project's general preference for honest measurement over reflexive
  action; rejected specifically because of the false-positive-only
  finding — this isn't a marginal accuracy difference to note and move
  on from, it's a measured, asymmetric safety gap in a guardrail whose
  job is exactly to catch that failure mode.

## Consequences
- `agent_decisions.model_used` now includes
  `claude-haiku-4-5-20251001` for every ticket that reaches drafting
  (it already did, for the draft itself) — no new entry in that field,
  just an additional real call under the same already-recorded model.
  Real incremental cost/latency impact will show up in
  `scripts/cost_report.py` going forward, same as ADR-0022's framing.
- `docs/capability-roadmap.md`'s Phase 17 deferred row ("Judge model
  comparison... Planned — deferred") is replaced by this phase's real
  entry — same pattern as Phase 18 replacing an earlier mis-scoped
  Planned row, not left duplicated.
- `test_groundedness_eval.py` (Ollama-only reliability study) is
  unchanged and still passes — it measures the Ollama path
  specifically, which is still real, still accurate, and still worth
  tracking even though production no longer relies on it for this
  check alone.
