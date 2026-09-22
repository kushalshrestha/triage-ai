# ADR-0023: Classification fallback routing (Ollama → Claude on parse failure)

**Status:** Accepted
**Date:** 2026-09-22

## Context
ADR-0022 (Phase 19) measured a real accuracy gap for ticket
classification — Ollama 0.67 vs. Claude 1.00 — and kept Ollama as the
production default anyway: classification runs on 100% of triage
volume (unlike drafting's partial volume) and is informational-only,
so paying for Claude on every call wasn't judged worth it.

Diagnosing *why* Ollama misses found the failures aren't random: for
harder tickets it sometimes returns a bare word (e.g. `"support"`) —
not one of the 4 valid categories — which the parser silently treated
as a miss, defaulting to `"bug"`. That's a **self-detecting**
failure: the code already knows, at the moment it happens, that
Ollama didn't give a usable answer. That changes the cost calculus
ADR-0022 was working from — instead of "send every ticket to Claude"
(rejected) or "never send any" (leaves the accuracy gap on the
table), a fallback that only calls Claude when Ollama's own output
fails to parse pays for Claude only on the subset that actually needs
it.

## Decision

### `classify_ticket_with_fallback()` — the new production path
`app/agent/classify.py`: `_match_category(raw) -> str | None` now
returns `None` instead of silently defaulting when nothing matches
(the existing pure `_classify_ticket_ollama()`, still used by
`classify_ticket(text, provider="ollama")` for eval comparisons, is
unchanged in behavior — `_match_category(raw) or DEFAULT_CATEGORY`).
`classify_ticket_with_fallback(text) -> tuple[str, bool]` tries Ollama
first; if `_match_category` returns `None`, it calls
`_classify_ticket_claude()` for that one ticket. If Claude itself
raises (network/API error), it's caught and falls back to
`DEFAULT_CATEGORY` — classification is informational, never worth
failing the whole triage pipeline over.

`app/agent/orchestrator.py::run_triage` now calls
`classify_ticket_with_fallback()` instead of `classify_ticket()`, and
appends `settings.claude_model_name` to `models_used` whenever the
fallback fires — even when the ticket never reaches drafting (e.g. it
escalates on retrieval similarity alone), because that's still a real
Claude API call that happened and needs to be reflected in cost/model
tracking, not silently absorbed into "just classification."

## Real measured result
Golden set: the same 12-example set from ADR-0022.

| Path | Accuracy | Fallback rate | Avg. latency/call |
|---|---|---|---|
| Ollama only (ADR-0022) | 0.67 | n/a | ~6.6s |
| Claude only (ADR-0022) | 1.00 | n/a | ~0.71s |
| **Fallback hybrid** | **1.00** | **58%** (7/12) | ~6.1s |

**The hybrid matches Claude's accuracy exactly, while only calling
Claude on 58% of tickets, not 100%.** That's a genuine, meaningful
result. It's also a *correction* of an estimate made in this ADR's own
early drafting: informal diagnosis before writing this ADR suggested
a ~33% fallback rate (counting only tickets where the old
default-to-`"bug"` behavior gave the *wrong* answer). The real
measured rate is higher — 58% — because it also fires for the "gave
an unparseable answer whose lucky bug-default happened to be right"
cases. That's the more honest number: it's every case where Ollama's
own output signaled it wasn't confident, not just the ones that were
visibly wrong before. Stated plainly rather than keeping the
lower, more flattering estimate.

**Latency is additive on the fallback path, not a wash**: a fallback
ticket pays Ollama's ~6.6s reload cost *and* Claude's ~0.7s round
trip, sequentially. The blended average above (~6.1s) looks close to
Ollama-alone's number only because more than half the calls in this
golden set take that slower, additive path.

Verified live against the running API (not just the eval): a real
ticket ("Any chance you will support two-factor authentication via an
app instead of SMS?") produced `reasoning`:
`"classified as 'feature_request' (Claude fallback); ..."` —
confirming the mechanism activates correctly end-to-end, not just
under test mocks.

## Alternatives considered
- **Keep ADR-0022's decision unchanged (Ollama only, no fallback)** —
  leaves a real, diagnosed, self-detecting failure mode uncorrected
  for no reason once a cheap, targeted fix exists.
- **Route all classification to Claude** — ADR-0022 already rejected
  this on 100%-volume/dependency grounds; still rejected, but this
  fallback captures most of the accuracy benefit at 58% of the volume
  instead of 100% — a real, if partial, improvement on that tradeoff,
  not a full reversal of it.
- **Retry Ollama once before falling back to Claude** — cheaper than
  calling Claude, but the failure mode observed (a bare category-
  adjacent word like `"support"`) looked like a systematic prompt/
  model-response pattern in ADR-0022's diagnosis, not transient
  noise — a same-input retry seemed unlikely to help and wasn't
  tested; worth a follow-up measurement if the real fallback rate at
  production volume turns out costlier than expected.

## Consequences
- No schema change — `models_used` already supported comma-separated
  multi-model tracking (ADR-0008 decision #5); this reuses it.
- `agent_decisions.reasoning` now says `"(Claude fallback)"` when it
  happened — visible in the API response and any future dashboard,
  not just inferable from `model_used`.
- The 58% real fallback rate means this is **not** a "free win" —
  ADR-0022's volume/dependency concern is reduced, not eliminated.
  Worth re-measuring against real production ticket volume once
  there is some (same caveat `docs/results.md`'s cost/latency section
  already states about `n=5` being too small to generalize from).
- `classify_ticket(text, provider=...)`'s existing signature and
  behavior are fully preserved — evals that need to measure a *pure*
  provider in isolation still can.
