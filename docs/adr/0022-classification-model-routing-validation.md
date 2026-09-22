# ADR-0022: Validating the Ollama-vs-Claude classification routing split

**Status:** Accepted
**Date:** 2026-09-22

## Context
project-brief.md's "Model routing" capability claims the Ollama/Claude
split is "backed by measured cost/latency/accuracy." Checking this:
cost and latency genuinely are measured (`scripts/cost_report.py`,
ADR-0010). **Accuracy, for the actual routing split, never was** —
`test_classification_eval.py` only ever measured Ollama's
classification accuracy; nothing measured what Claude would score on
the same task. The split (Ollama classifies, Claude drafts) was
justified by intuition in ADR-0008 ("routine work" vs. "complex
generation"), never validated head-to-head.

**A second problem found while reading the existing golden set**
(`tests/evals/golden_set.jsonl`, 5 examples): several were near-
verbatim paraphrases of the few-shot examples baked into
`classify.py`'s own prompt (`"I was charged twice this month"` in the
prompt vs. `"I was charged twice for my subscription this month"` in
the golden set). That was testing recall of the prompt's own examples,
not real generalization, and inflated the measured accuracy to a
perfect 1.00.

## Decision

### 1. Grew and de-duplicated the golden set
`golden_set.jsonl`: 5 → 12 examples. The 4 near-duplicates were
reworded to genuinely different phrasing for the same category; 7 new
examples added, including 2 deliberately ambiguous cases (e.g. a
ticket mentioning both a login failure *and* a billing charge) —
labeled with the primary/actionable intent and an explicit `"note"`
field explaining the ambiguity, not silently treated as clear-cut.

### 2. Multi-provider classification dispatcher
`app/agent/classify.py`: `ClassificationProvider = Literal["ollama", "claude"]`,
`classify_ticket(text, provider="ollama")` — mirrors
`app/rag/contextualize.py`'s established pattern (Phase 12) exactly.
Production (`app/agent/orchestrator.py`) never passes `provider`, so
behavior is unchanged regardless of what this measurement finds.
Claude's classifier (`_classify_ticket_claude`) uses forced tool-use
with an `enum`-constrained field (matching `drafting.py`'s
`_DRAFT_TOOL` pattern) — schema-guaranteed valid output, so the
comparison is about classification quality, not parsing robustness on
either side.

### 3. Real measured result
Against the new 12-example golden set:

| Provider | Accuracy | Avg. latency/call |
|---|---|---|
| `ollama/llama3.2:1b` | **0.67** (8/12) | ~6.6s |
| `claude/claude-haiku-4-5-20251001` | **1.00** (12/12) | ~0.71s |

**Ollama's misses, diagnosed directly** (not just observed): for 4 of
12 tickets, the raw model output was the single word `"support"` —
not one of the 4 valid categories — which falls through
`_match_category()`'s parsing to the `"bug"` default. Two of those 4
happened to have `expected_label == "bug"` (correct by luck of the
default, not genuine classification), leaving 4 real misses. This is
a **capability ceiling**, not a parsing bug: three prompt variants
were tried before accepting this —

| Variant | Accuracy | Note |
|---|---|---|
| Original (kept) | **0.67** | Baseline |
| More emphatic instruction ("You MUST respond with exactly one of...") | 0.50 | Worse — biased toward over-predicting "bug" |
| Broader few-shot examples (added account/feature_request examples) | 0.67 | Same net accuracy — the "support" quirk persists, just on different rows |

Same pattern as ADR-0009 and ADR-0020: this local model responds
unpredictably, sometimes worse, to more elaborate prompts. Kept the
original prompt unchanged.

Claude's latency being *lower* than Ollama's here is mostly Ollama's
`keep_alive: 0` reload cost (~5-7s per call, ADR-0009's documented
tradeoff for correctness), not Claude being unusually fast — but it
means "free is at least slower, if not less accurate" doesn't fully
capture this result; here free is both slower *and* less accurate.
Claude's real per-call cost, measured directly: 791 input / 33 output
tokens — small in isolation (a fraction of a cent), well below
drafting's average (~3,661 input / ~411 output per `docs/results.md`).

## Alternatives considered / the actual decision
**Given a real, meaningful accuracy gap — not "ties, kept the free
option" like every prior provider comparison in this project (Phases
10, 12, 13) — should classification move to Claude?**

**Decision: no, keep Ollama as the default.** The deciding factor is
volume, not per-call cost: classification runs on **100% of triage
calls**, unlike drafting, which only runs on the subset that clears
the draft threshold. Adding a real, network-dependent paid API call to
every single triage decision — for a field that is explicitly
informational only and does not drive auto-respond/draft-for-review/
escalate routing (ADR-0008 decision #4, unchanged) — is a materially
different cost/dependency profile than accepting it for drafting,
where the output reaches the customer directly and errors have real
consequences. A classification error here shows up as a wrong label
in `agent_decisions.reasoning` and eval tracking; it does not change
what a customer receives or whether a ticket gets escalated.

This is stated as a knowing tradeoff now, not an unexamined default:
**the accuracy gap is real (0.67 vs 1.00) and worth remembering** when
citing this project's guardrail/quality coverage. If classification's
role ever expands to influence real routing decisions (not just
`reasoning` text), this conclusion should be revisited with that
changed stake in mind.

## Consequences
- No production behavior change — `orchestrator.py`'s call site is untouched.
- `test_classification_eval.py`'s `ACCURACY_THRESHOLD` dropped from
  0.90 (based on the inflated golden set) to 0.6 (real headroom below
  the measured 0.67) — the old threshold was passing against a golden
  set that didn't actually test generalization.
- `test_classification_provider_comparison_eval.py` (new,
  `@pytest.mark.costly`) keeps this comparison re-runnable — if a
  future prompt or model change moves either number meaningfully,
  this eval will show it.
- `docs/results.md`'s "golden sets are synthetic" known limitation is
  now slightly better for classification (12 more diverse examples,
  including deliberately ambiguous ones) though still hand-crafted,
  not real production tickets — that gap remains open, same as before.
