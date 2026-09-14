# AI architecture

This is the document that does the most work in an interview — it's
where "I called an API" becomes "I engineered a system." Fill each
section in as the corresponding build phase lands; don't leave this
as placeholder text by the time you're presenting the project.

## RAG design
- **Chunking strategy:** fixed-size character windows, 800 characters
  with 100-character overlap (`app/rag/chunking.py`). No tokenizer
  dependency, fully deterministic. See ADR-0007 for why, and for the
  semantic-chunking alternative considered and deferred.
- **Embedding model:** `sentence-transformers`/`all-MiniLM-L6-v2`
  (384-dim), run in-process in the `api` container — not Ollama, despite
  the "Ollama-hosted for local work" framing elsewhere in this doc; see
  ADR-0007 for the disk-budget reasoning. `doc_chunks.embedding` is
  `vector(384)`.
- **Retrieval:** top-k cosine-similarity search against
  `doc_chunks.embedding` (`app/rag/retrieval.py`), joined to originating
  `knowledge_docs`. k=3 is the current starting value — not yet tuned
  against real eval data; `tests/evals/test_retrieval_eval.py` is the
  mechanism for tuning it with actual numbers later.
- **Faithfulness:** how eval measures whether a response is actually
  grounded in what was retrieved, vs. hallucinated.

## Agent design
- **Decision space:** auto-respond / draft-for-review / escalate.
- **Tool calls:** what the agent can invoke beyond retrieval (e.g.
  account/SLA lookup) and how those results factor into the decision.
- **Confidence threshold:** the number that triggers escalation, and
  how it was chosen (start with a guess, then justify it with eval
  data once the golden set has run against it).

## Model routing (LLMOps)
- **Ollama (local):** which model, why this size, what it's used for
  (routine classification).
- **Claude (hosted):** what it's used for (complex draft generation),
  and why that split rather than one model for everything.
- **Routing decision data:** link to the cost/latency/accuracy
  comparison once it exists (see project-brief.md open items).
- **Prompt versioning:** how prompt changes are tracked and tied to
  eval runs, so a regression can be traced to a specific version.

## Evaluation framework
- **Golden set:** size, how examples were sourced (synthetic vs. real,
  see project-brief.md), how it's kept representative over time.
- **Metrics:** classification accuracy, RAG faithfulness, LLM-as-judge
  quality score — thresholds for each, and what happens when a run
  falls below threshold.
- **CI gate:** smoke subset on every PR, full set nightly/pre-release.

## Guardrails and safety
- **Input side:** injection detection, PII redaction — current
  implementation is pattern-based (see `app/guardrails/injection.py`);
  document if/when this moves to a classifier.
- **Output side:** schema validation, hallucination check against
  retrieved context.
- **Red-team set:** how adversarial examples are sourced and grown
  over time (`tests/evals/test_safety_eval.py`), and results of the
  latest run.

## Open questions
Track unresolved design decisions here until they're settled, then
move the resolution into an ADR.
