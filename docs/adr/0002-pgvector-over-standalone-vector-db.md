# ADR-0002: Use pgvector inside Postgres instead of a standalone vector DB

**Status:** Accepted
**Date:** 2026-09-13

## Context
The RAG pipeline needs to store and query embeddings for knowledge-base
chunks. Standalone vector DBs (Pinecone, Weaviate, Qdrant) are common
choices, but this is a single-developer portfolio project on a modest
ticket volume, not a system with 100M+ vector scale.

## Decision
Store embeddings in a `vector` column on `doc_chunks`, inside the same
Postgres instance as the relational ticket data (see schema in
`system-architecture.md`).

## Alternatives considered
- **Standalone vector DB** — better at very large scale and ANN search
  tuning, but adds a second system to run, secure, and back up for no
  benefit at this project's scale. Worth a follow-up ADR if/when scale
  actually demands it.

## Consequences
- One fewer moving part in `docker-compose.yml`.
- Retrieval joins directly against relational ticket/decision data in a
  single query instead of round-tripping between two systems.
- Revisit if embedding volume or query latency ever becomes a real
  bottleneck — that would be its own ADR with real numbers behind it,
  not a guess made now.
