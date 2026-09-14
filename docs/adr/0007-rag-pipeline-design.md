# ADR-0007: RAG pipeline design — chunking, embeddings, retrieval

**Status:** Accepted
**Date:** 2026-09-14

## Context
`docs/ai-architecture.md`'s RAG section had three open "TBD" items:
chunking strategy, embedding model, and the retrieval k value. Building
phase 3 (ingestion + retrieval) means actually deciding these, not
leaving them as placeholders. ADR-0004 had already provisioned
`doc_chunks.embedding` as `vector(768)` on the assumption of an
Ollama-hosted `nomic-embed-text` model, explicitly flagged there as
"revisit once the embedding model is chosen." Ollama has since failed
to even pull its base image twice in this environment (disk budget
exhausted both times), which forces that revisit now rather than later.

## Decision
1. **Embedding model: `sentence-transformers`, `all-MiniLM-L6-v2`
   (384-dim)**, run in-process inside the `api` container. Supersedes
   ADR-0004's provisional `vector(768)`/Ollama assumption —
   `doc_chunks.embedding` changes to `vector(384)` via a new migration.
   No data existed yet to migrate, so this is a clean column-type
   change, not a backfill. This is a divergence from
   `project-brief.md`'s "Ollama-hosted for routine local work" framing,
   but that framing was written about classification/generation
   routing, not embeddings specifically — and a ~90MB pip-installed
   model avoids a disk problem that has already blocked this project
   twice.
2. **Chunking: fixed-size character windows — 800 characters, 100
   character overlap.** No tokenizer dependency, fully deterministic,
   easy to unit test. Reasonable default for FAQ/knowledge-doc-length
   content; revisit toward semantic (heading/paragraph-aware) chunking
   if real documents turn out to need it.
3. **Retrieval: cosine similarity via pgvector, k=3.** A starting
   value, not yet tuned against real eval data — recorded here per
   `ai-architecture.md`'s own note to write down k "once tuned," with
   the retrieval eval (`tests/evals/test_retrieval_eval.py`) as the
   mechanism for tuning it later with actual numbers instead of a
   guess.
4. **Knowledge ingestion is staff-only** (`agent`/`admin`, via the
   existing `require_role` dependency from ADR-0005). Partial
   mitigation for `docs/threat-model.md` threat #8 (a malicious document
   poisoning the knowledge base via ingestion) — a full source
   allowlist/review step remains an open question there, this just
   closes the "anyone can inject documents" gap. Search
   (`GET /knowledge/search`) stays open to any authenticated user, since
   it's meant to eventually support self-service lookups for customers
   too, per the README's "agent-assisted reply view" framing.
5. **HF model cache in a named Docker volume** (`hf_cache`, mounted at
   the HuggingFace cache path in the `api` service), so rebuilding the
   image doesn't force re-downloading the model weights every time.

## Alternatives considered
- **Keep Ollama `nomic-embed-text` at 768-dim** — matches the original
  plan and needs no schema change, but blocks phase 3 entirely until
  the disk-budget problem is solved, which has failed twice already
  this session and isn't this phase's problem to solve.
- **`fastembed` (ONNX-based, no `torch`)** — a lighter-weight
  alternative that would avoid pulling in `torch` at all. Considered,
  but `sentence-transformers` is the more widely recognized choice for
  this kind of local-embedding story, and the Docker VM had enough
  headroom (21.6GB free) at decision time that the smaller footprint
  wasn't necessary. Worth switching to if disk pressure recurs.
- **Token-aware chunking (e.g. via `tiktoken`)** — more accurate chunk
  sizing relative to what a model actually sees, but adds a dependency
  and complexity not justified before real retrieval-quality data shows
  character-based chunking is actually a problem.

## Consequences
- `doc_chunks.embedding` is `vector(384)` now; any future embedding
  model change is again a migration, not a config flag — expected and
  accepted, same as ADR-0004's original tradeoff.
- The retrieval eval's dataset is the first real feedback loop for
  tuning chunk size, overlap, and k — those are hand-picked defaults
  until it says otherwise.
- Retrieval is a standalone function/endpoint in this phase, not yet
  writing to the `retrievals` table (which is scoped to an
  `agent_decision_id` that doesn't exist until phase 5's agent
  orchestration creates one). This phase is a building block, not the
  full grounded-response pipeline yet.
