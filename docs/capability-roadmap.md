# Capability roadmap

Starting with Phase 9, phases increment as one continuous sequence
across all capabilities (knowledge ingestion, agent orchestration,
guardrails, LLMOps, etc.) rather than restarting the count per
capability. This file is the single source of truth for "what phase
are we on" — update the Status column as part of finishing a phase,
not as an afterthought.

| Phase | Capability | What | Status |
|---|---|---|---|
| 1–8 | (original build sequence) | Schema → Auth/CRUD → Frontend → RAG → Agent → Guardrails → LLMOps → Packaging | Done |
| 9 | Knowledge Ingestion | Retrieval eval (chunk-level recall@k + MRR@k, see ADR-0012) | Done |
| 10 | Knowledge Ingestion | Hybrid search + RRF (see ADR-0013 — implemented; no measurable win yet on this eval corpus) | Done |
| 11 | Knowledge Ingestion | Golden-set realism — real customer-support FAQ corpus (see ADR-0014) | Done |
| 12 | Knowledge Ingestion | Contextual retrieval (see ADR-0015 — implemented, opt-in; no measurable win on the one multi-chunk doc tested) | Done |
| 13 | Knowledge Ingestion | Cross-encoder re-ranking (see ADR-0016 — implemented, opt-in; targeted a real diagnosed failure, partially fixed it, net MRR worse due to 2 new regressions) | Done |
| 14 | Knowledge Ingestion | Ingestion hardening — background chunk/embed via `BackgroundTasks`, no size cap (see ADR-0017); admin approve/reject workflow closing threat-model item #8 | Done |
| 15 | Guardrails | Rate limiting on AI-facing endpoints — in-memory per-user fixed-window limiter, no new infra (see ADR-0018); closes threat-model item #4 | Done |
