# ADR-0030: Real tracing/observability via OpenTelemetry + Jaeger

**Status:** Accepted
**Date:** 2026-11-15

## Context
Second of 4 deferred enhancements tracked in `docs/capability-roadmap.md`.
project-brief.md's tech stack has named "Tracing/observability:
Langfuse (or similar) for per-call latency, cost, eval score" since
the project's original scope — flagged as a stretch item to cut if
behind, and never built. `scripts/cost_report.py` (ADR-0010) is a
deliberate on-demand report generator over `agent_decisions`, not live
per-call tracing. `docs/ai-architecture.md`'s Open Questions has
carried "standing up real tracing is a bigger infra lift... than any
phase so far has scoped in" since Phase 7.

## Decision
**OpenTelemetry (OTel) instrumentation + self-hosted Jaeger as the
trace backend**, using OTel's GenAI semantic conventions
(`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`) for LLM-specific span attributes.

**Why OTel, not a vendor SDK directly:** OpenTelemetry is the
vendor-neutral industry standard for distributed tracing — instrument
once with the OTel SDK/semantic conventions, and the trace data is
portable to any OTLP-compatible backend (Jaeger, Langfuse, Honeycomb,
Datadog, Grafana Tempo) without touching instrumentation code later.
**Why Jaeger, not Langfuse specifically** (despite project-brief.md
naming it): Langfuse's current self-hosted stack is multiple services
(its own DB, cache, etc.) — a bigger infra lift than this project's
scale justifies, the same reasoning ADR-0017 already applied to
deferring a real task queue. Jaeger is a single container, speaks OTLP
natively, is itself a CNCF/OTel reference implementation (not vendor
lock-in), and needed no new external account — consistent with this
project's "all local dev runs through docker compose" rule. If
Langfuse (or another backend) is ever adopted later, only the exporter
endpoint changes, not the instrumentation code.

### Implementation
- **`docker-compose.yml`**: new `jaeger` service
  (`jaegertracing/all-in-one:1.57`), OTLP ports 4317/4318 + UI 16686.
- **`app/tracing.py`** (new): `setup_tracing()` builds a
  `TracerProvider` with a `BatchSpanProcessor` (async background
  export — never blocks a request on exporter latency/failure, the
  standard production choice over `SimpleSpanProcessor`) and an OTLP
  gRPC exporter. Called once from `main.py`, followed by
  `FastAPIInstrumentor.instrument_app(app)` — auto-creates the root
  span for every HTTP request, the parent of everything below via
  OTel's automatic context propagation.
- **`app/agent/ollama_client.py::generate_raw`** — the one shared
  funnel every Ollama caller (`classify.py`, `judge.py`, `quality.py`,
  `contextualize.py`) already goes through; one span here covers every
  Ollama call site for free. Also started capturing
  `prompt_eval_count`/`eval_count` from Ollama's own response JSON
  (already returned, previously discarded) as real
  `gen_ai.usage.input_tokens`/`output_tokens`.
- **Claude call sites** (no shared funnel exists): a span wraps each
  `client.messages.create(...)` individually in `classify.py`,
  `judge.py`, `drafting.py` (production path) and `quality.py`,
  `rag/contextualize.py` (eval/opt-in paths) — `gen_ai.usage.*` comes
  straight from `message.usage`, already computed at each site.
- **`orchestrator.py::run_triage`** — kept the original function body
  entirely intact as `_run_triage`; a new thin `run_triage` wrapper
  opens the parent span and reads `triage.decision_type`,
  `triage.model_used`, `triage.confidence_score` off the *returned*
  `AgentDecision` object. Chosen over re-indenting the ~250-line
  function body: smaller diff, zero risk of introducing a bug in
  already-working logic, same result.

### A real, version-compatibility finding worth recording
The plan's own stated unknown was exact package versions — this
surfaced for real, not hypothetically: `opentelemetry-instrumentation-fastapi==0.48b0`
(a reasonable-looking pin at planning time) crashed on every single
request — `AttributeError: '_IncludedRouter' object has no attribute
'path'` — because its internal Starlette route-matching code predates
this project's `starlette==1.6.0`. A plain import check passed; the
incompatibility only showed up when actually exercising the
instrumentation against real requests, confirming the plan's own
instinct to verify empirically rather than trust a version pin at
install time. Fixed by upgrading the whole OTel package set together
(`opentelemetry-api`/`sdk`/`exporter-otlp-proto-grpc` 1.27.0 → 1.45.2,
`opentelemetry-instrumentation-fastapi` 0.48b0 → 0.66b2) — resolved and
re-verified against the full test suite before locking in the pins.

## Real verification — an actual captured trace, not a claim
Triggered a real `run_triage()` call (real Ollama classification, real
Claude fallback, real Claude drafting, real Claude groundedness) and
queried it back from Jaeger's API
(`GET /api/traces?service=triageai-api&operation=run_triage`):

```
run_triage (27.8s total)
  ├─ ollama_generate         gen_ai.usage: 192 in / 2 out tokens
  ├─ claude_classify         gen_ai.usage: 793 in / 33 out tokens
  ├─ claude_generate_draft   gen_ai.usage: 942 in / 135 out tokens
  └─ claude_assess_groundedness  gen_ai.usage: 849 in / 34 out tokens
```

This is a genuinely informative trace, not just a structural proof:
`ollama_generate` immediately followed by `claude_classify` in the
same request visibly shows ADR-0023's classification fallback firing
in real time (Ollama's classification output didn't parse, so Claude
was called for just this ticket) — the kind of thing that was
previously only inferable from `agent_decisions.model_used` after the
fact, now visible as the actual causal sequence in a trace.
`triage.decision_type=draft_for_review` and
`triage.model_used=ollama/llama3.2:1b,claude-haiku-4-5-20251001` on the
parent span match the real `AgentDecision` persisted for this ticket.

Separately, a real HTTP-level request (via the test suite's
`TestClient`, which goes through the full ASGI app) confirmed the
intended parent-child structure end-to-end: `POST
/tickets/{ticket_id}/triage` (FastAPI's auto-instrumented root span) →
`run_triage` (manual span) — proving the auto-instrumentation and
manual spans nest correctly, not just that each works in isolation.

## Alternatives considered
- **Langfuse (named in project-brief.md)** — see above; its current
  self-hosted footprint is a bigger lift than this project's scale
  justifies. Revisit if this project ever needs Langfuse-specific
  features (prompt management, eval-score-alongside-traces) that
  Jaeger's generic tracing UI doesn't offer — the OTel instrumentation
  underneath wouldn't need to change.
- **A shared Claude-call wrapper** (to avoid repeating the span
  boilerplate across 5 call sites) — considered and rejected as scope
  creep: this phase is about adding tracing, not restructuring how
  Claude clients are created across the codebase. Each site keeps its
  existing shape; only a span context manager was added.

## Consequences
- No schema change, no new `GuardrailCheckType` — tracing is a
  parallel, read-only observability layer over the exact same model
  calls already happening; it doesn't change `agent_decisions` or any
  persisted data.
- `scripts/cost_report.py` is unchanged and still useful — historical
  DB aggregation and live per-call tracing answer different questions
  (trend over time vs. what happened on this one request), not a
  replacement relationship.
- `docs/ai-architecture.md`'s long-standing "Tracing / cost dashboard"
  Open Question is closed for real, not just reworded.
- Jaeger's default in-memory storage means traces don't survive a
  container restart — acceptable for local dev/demo (the stated scope
  here); a persistent trace storage backend (Elasticsearch/Cassandra,
  Jaeger's supported options) is a separate, later decision if this
  project's tracing needs ever go beyond local development.
