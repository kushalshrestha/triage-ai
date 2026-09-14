# TriageAI

An AI-native support ticketing platform — not a chatbot bolted onto a CRUD
app, but a system built around retrieval, agentic decision-making,
evaluation, and guardrails as first-class components.

## Why this exists
Most "AI-powered SaaS clone" portfolio projects demonstrate one skill:
calling an LLM API. TriageAI is built to demonstrate the platform layer
around that call — the parts that actually distinguish an AI Platform
Engineer: how you route between models, how you know the system is still
working after a prompt change, and how you stop it being trivially abused.

See `docs/system-architecture.md` and `docs/ai-architecture.md` for the
full design, and `docs/adr/` for the reasoning behind specific decisions.

## What's here
- **RAG** — knowledge base chunked and embedded in pgvector, grounded
  retrieval feeds every draft response
- **Agentic triage** — retrieves context, looks up real requester account
  data (age, prior ticket count), decides auto-respond / draft-for-review
  / escalate based on retrieval confidence
- **Model routing (LLMOps)** — routine classification via a local model on
  Ollama, complex drafting via Claude, cost/latency captured per decision
  (`docs/results.md`, `scripts/cost_report.py`)
- **Evals** — a golden set and offline metrics from day one, growing with
  each phase rather than bolted on at the end (`docs/testing-strategy.md`);
  results in `docs/results.md`
- **Guardrails** — input-side injection detection and PII redaction,
  output-side schema validation (forced Claude tool-use) and an
  independent groundedness check, a growing red-team suite
- **Two dashboards** — a customer-facing ticket view and a staff view
  that can trigger triage and see the drafted reply, confidence, and
  guardrail results inline

## Running it locally
```
cp backend/.env.example backend/.env   # add your ANTHROPIC_API_KEY
docker compose up
```
API: `http://localhost:8000` · Frontend: `http://localhost:5173`

## Status
Phases 1–7 of the build (schema → auth/CRUD → RAG → guardrails → agent
orchestration → output guardrails → a first LLMOps pass) are done, along
with both dashboards. See `docs/ai-architecture.md` for what's filled in
vs. still open, `docs/results.md` for real eval/safety/cost numbers, and
`docs/demo-script.md` for a guided walkthrough of the system end to end.
