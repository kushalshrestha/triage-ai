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
- **Decision space:** auto-respond / draft-for-review / escalate,
  implemented in `app/agent/orchestrator.py::run_triage`, triggered
  manually via `POST /tickets/{id}/triage` (not automatic on ticket
  creation — see ADR-0008 for the cost/latency reasoning).
- **Tool calls:** `app/agent/tools.py::get_account_context` — requester
  account age and prior ticket count, both already in the schema. Folds
  into the Claude drafting prompt and into `agent_decisions.reasoning`;
  does not change the routing decision itself.
- **Confidence threshold:** routing comes from the top RAG retrieval's
  cosine similarity (not a separate model call — see ADR-0008 for why).
  Starting guesses: `< 0.5` → escalate, `0.5–0.8` → draft-for-review,
  `≥ 0.8` → auto-respond. `tests/evals/test_triage_eval.py` is the
  mechanism for revisiting these with real accuracy data.

## Model routing (LLMOps)
- **Ollama (local):** `llama3.2:1b`, used for routine ticket
  classification (`app/agent/classify.py`) — a category label
  (billing/bug/account/feature_request) that's informational (tracked
  via `tests/evals/test_classification_eval.py`) and doesn't drive
  routing.
- **Claude (hosted):** `claude-haiku-4-5-20251001` (configurable via
  `Settings.claude_model_name`), used for grounded draft generation
  (`app/agent/drafting.py`) once retrieval similarity clears the
  draft-for-review/auto-respond threshold. Split rationale: classifying
  a ticket into one of four labels is exactly the "routine, cheap,
  local" work Ollama is for; drafting a coherent, grounded reply from
  retrieved context is the "complex generation" work worth paying for.
- **Routing decision data:** not yet collected — `agent_decisions` rows
  now exist with real `model_used` values (ADR-0008 closes
  `docs/threat-model.md` threat #7), so the cost/latency/accuracy
  comparison from `project-brief.md`'s open items can be computed from
  real data going forward, just hasn't been analyzed yet.
- **Prompt versioning:** not yet implemented — `app/agent/classify.py`
  and `app/agent/drafting.py`'s prompts are inline string templates with
  no version tag. Open question, tracked below.

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
- **Prompt versioning:** `app/agent/classify.py` and
  `app/agent/drafting.py` have no version tag on their prompts yet, so
  a regression can't be traced to a specific prompt version. Needs a
  scheme (even a simple constant per prompt) before the eval-gate story
  in `testing-strategy.md` can actually catch a prompt-change
  regression.
- **Output-side guardrails** (schema validation, LLM-judge groundedness
  score against retrieved context) are phase 6 scope — not built yet,
  see ADR-0008.
