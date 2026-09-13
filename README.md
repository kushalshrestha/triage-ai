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
- **Agentic triage** — retrieves context, checks account/SLA state, decides
  auto-respond / draft-for-review / escalate
- **Model routing (LLMOps)** — routine classification via a local model on
  Ollama, complex drafting via Claude, routing backed by measured cost and
  latency, not preference
- **Evals** — a golden set and offline metrics from day one, growing with
  each phase rather than bolted on at the end (`docs/testing-strategy.md`)
- **Guardrails** — input-side injection detection and PII redaction,
  output-side schema and groundedness checks, a growing red-team suite

## Running it locally
```
cp backend/.env.example backend/.env   # add your ANTHROPIC_API_KEY
docker compose up
```
API: `http://localhost:8000` · Frontend: `http://localhost:5173`

## Status
Early scaffold — schema and guardrail unit/safety tests are in place and
passing; RAG, agent orchestration, and the full eval/LLMOps layer are in
progress. See `docs/ai-architecture.md` for what's filled in vs. still open.
