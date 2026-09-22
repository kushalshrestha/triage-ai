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
| 16 | Grounded Retrieval | Citation-scoped groundedness verification — checks drafts against only the chunks they actually cite, not the whole retrieved pool; persists `Retrieval.cited`; surfaces real citations to reviewers, including each citation's similarity score (see ADR-0019) | Done |
| 17 | Evaluation Framework | Groundedness judge reliability study — real golden set (11 examples), measured consistency (1.0) and accuracy (0.636) for the current prompt; three rewrites tried and measured worse, kept as-is (see ADR-0020) | Done |
| — | Evaluation Framework | Judge model comparison — ADR-0020 measured a 0.636 accuracy ceiling for `llama3.2:1b` on groundedness; try a larger local Ollama model (free) and/or Claude (real cost, same tradeoff pattern as Phase 12's contextual-retrieval comparison) against the same golden set | Planned — deferred, not part of Grounded Retrieval |
| 18 | Triage Agent | Cited-chunk confidence check — downgrades `auto_respond` → `draft_for_review` when the actually-cited chunk's similarity falls short, even if the top-retrieved chunk cleared the bar; plus a real, free, 15-example triage routing-accuracy eval against the MakTek corpus (measured 15/15) validating the 0.5/0.8 thresholds for the first time with real data (see ADR-0021) | Done |
| 19 | Model Routing | Validated the Ollama-vs-Claude classification split with real accuracy numbers for the first time — found the golden set was inflated by few-shot duplication, fixed it, measured a real gap (Ollama 0.67 vs Claude 1.00); kept Ollama as default given classification is informational-only and runs on 100% of triage volume, not just the drafting subset (see ADR-0022) | Done |
| 20 | Model Routing | Classification fallback routing — Ollama first, Claude only when Ollama's own output fails to parse (a real, self-detecting failure mode from ADR-0022); measured 1.00 accuracy (matches Claude-only) at a 58% Claude-call rate, not 100% (see ADR-0023) | Done |
