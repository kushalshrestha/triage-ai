# ADR-0024: Prompt regression-baseline snapshots

**Status:** Accepted
**Date:** 2026-09-22

## Context
project-brief.md's "Prompt versioning + CI eval gate" capability:
"Prompt/model changes blocked until eval suite passes." Auditing this
found a split result:

- **The CI eval gate genuinely works** — `eval-smoke` blocks every PR
  on hardcoded per-eval thresholds, proven twice this session for real
  (the groundedness and classification CI failures, ADR-0020 and the
  fix documented in ADR-0022, both actually blocked, for real
  cross-architecture reasons, and got fixed properly).
- **"Prompt versioning" existed but had never been used for its
  intended purpose.** Every `PROMPT_VERSION` constant (`classify.py`,
  `drafting.py`, `judge.py`, `contextualize.py`) was still `"v1"`.
  `eval_runs.prompt_version` was write-only — nothing ever read or
  compared it. Every real prompt-variant experiment this session (the
  groundedness judge's 3 rewrites, ADR-0020; classification's 3
  variants, ADR-0022) bypassed the mechanism entirely, run as
  throwaway diagnostic scripts instead of a real `PROMPT_VERSION` bump
  captured anywhere comparable. ADR-0010 deferred building "compare
  against last-known-good version" tooling as "premature until a
  second prompt version exists" — that trigger condition had already
  been met three times over, just never through the intended channel.

**A design correction made before building anything**, worth stating
plainly since it changed the whole approach: a live-`eval_runs`-
history comparison was the first instinct, but it doesn't work.
`tests/evals/conftest.py::record_eval_run` writes to the real app
engine, and in CI that's a fresh, ephemeral Postgres service container
per workflow run — **CI's `eval_runs` table is empty at the start of
every single run.** There is no cross-run history to query in CI at
all. `docs/testing-strategy.md` layer 5 already named the actually-
correct design — "golden-set scores get snapshotted per prompt/model
version" — a committed file, which persists across CI runs the way a
live ephemeral DB can't. That was written down long before this ADR
and never built; this phase finally builds it.

## Decision

### A committed JSON snapshot, not a live query
`tests/evals/regression_baseline.json` — one entry per
`(run_type, model_used, metric)`, seeded with the real measured v1
baselines already established in ADR-0020 (groundedness) and ADR-0022
(classification), not placeholders.

### A small, pure comparison module + fixture
`tests/evals/regression.py`: `load_baseline()`, `get_baseline_entry(...)`,
and `check_regression(current_score, baseline_score, tolerance=0.1)`.
The tolerance is **not** zero — real cross-architecture inference
variance for an *unchanged* prompt was already measured at ~0.09 on a
12-example set (the classification CI incident). A zero-tolerance
comparison would false-positive on that noise alone; 0.1 was chosen
with that real number in hand.

`tests/evals/conftest.py::assert_no_regression(run_type, model_used, score, metric=None)`
wraps this as a fixture: no baseline entry yet → pass (nothing to
compare against); entry exists and the drop exceeds tolerance → fail
with a message telling the developer to update
`regression_baseline.json` deliberately if the change was intentional.
Never auto-updated by CI — the same manual-acknowledgment convention
snapshot-testing tools (Jest, syrupy) already use elsewhere in the
industry.

### Wired into the two evals with real prompt-variant history
`test_classification_eval.py` and `test_groundedness_eval.py` call
`assert_no_regression(...)` alongside their existing hardcoded-
threshold assertions. No new CI job — both already run in `eval-smoke`
on every PR; the new check just reads a committed file, no DB query,
no new infrastructure. Not extended to retrieval or triage-routing
this phase — those are threshold/algorithm-driven, not a tunable
prompt string, so a version-history regression check doesn't apply to
them the same way; scoping to the two evals with actual real
experiment history keeps this an honest first pass, not speculative
coverage everywhere.

## Real demonstration, not just synthetic unit tests
Locally, temporarily: `classify.py`'s `PROMPT_VERSION` was set to a
demo value and the prompt swapped for ADR-0022's already-measured
"more emphatic instruction" variant (0.50 accuracy) — **without**
touching `regression_baseline.json`. Running `test_classification_eval.py`
produced this real failure:

```
E       AssertionError: Regression detected for classification/ollama/llama3.2:1b:
        score 0.500 is below the committed baseline 0.670 (prompt_version='v1')
        by more than the tolerance. If this prompt/model change is intentional,
        update tests/evals/regression_baseline.json deliberately, in this same
        change, rather than silently accepting a worse score.
1 failed in 88.94s
```

**This is a stronger proof than expected going in**: `ACCURACY_THRESHOLD`
is `0.5`, and the demo variant measured exactly `0.500` — the existing
flat-threshold assertion (`accuracy >= 0.5`) would have **passed** this
regression outright. Only the new regression-baseline check caught it.
That's a concrete, real case of exactly the gap this phase closes: a
flat floor alone can miss a real, meaningful drop that still clears
the floor. `classify.py` was reverted to `v1` immediately after (`git
diff` confirmed a clean, exact revert) — no broken intermediate state
was ever committed.

## Alternatives considered
- **Query `eval_runs` history directly in CI** — the original instinct;
  rejected once it became clear CI's Postgres is ephemeral per run and
  holds no cross-run history at all. Would need a persistent database
  outside CI's own service containers to work, which is more
  infrastructure than this deserves for a first pass.
- **Auto-update the baseline file from CI when a score improves** —
  rejected: silently ratcheting a committed baseline from automation
  risks masking a slow sequence of small regressions, each individually
  "not worse than last time." A human explicitly updating the file is
  the same deliberate-acknowledgment step every real snapshot-testing
  convention already requires.
- **Apply this to every eval immediately** — rejected as premature
  breadth: retrieval and triage-routing don't have a tunable prompt in
  the same sense; scoping to the two evals with genuine prior
  experiment history is the honest "first pass" this project has
  consistently favored (ADR-0010's own framing) over speculative
  coverage.

## Consequences
- No schema change, no new CI job, no new production dependency —
  purely test/eval infrastructure, a committed JSON file plus a small
  pure module.
- `docs/testing-strategy.md` layer 5 now describes something actually
  implemented, not an aspirational design that was written down once
  and never built.
- The next time a prompt genuinely changes (a real v2, not a
  throwaway diagnostic script), the workflow is: change the prompt,
  bump `PROMPT_VERSION`, run the eval, and if the new score is
  accepted, update `regression_baseline.json` in the same change. If
  it regresses and that's not intentional, this mechanism is exactly
  what catches it before merge — which is what "prompt/model changes
  blocked until eval suite passes" was always supposed to mean.
