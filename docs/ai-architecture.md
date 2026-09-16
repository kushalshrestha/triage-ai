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
- **Contextual retrieval (Phase 12, ADR-0015):** opt-in, off by
  default — `ingest_document(..., use_contextual_retrieval=True)`
  prepends a Claude-generated blurb situating each chunk within its
  parent document before embedding, but only for documents that
  produced more than one chunk (a single chunk already contains 100%
  of its own context). Given almost every document in this project's
  corpus is single-chunk, this triggers rarely by design. Measured
  result on the one multi-section document built specifically to test
  it: recall@3 = 1.0 both with and without; MRR@3 went from 0.90
  (without) to 0.87 (with) — contextualization didn't help here, and
  the reason is understood (a chunk genuinely straddling two topics
  got a context blurb that made it look *more* similar to a
  neighboring chunk's query, not less). Not enabled by default as a
  result; the generated blurb is stored separately
  (`doc_chunks.context_prefix`), never mixed into `content`.
- **Retrieval:** hybrid search as of Phase 10 (`app/rag/retrieval.py`,
  see ADR-0013) — top-10 candidates from cosine-similarity search
  against `doc_chunks.embedding` plus top-10 from Postgres full-text
  search (`to_tsvector`/`plainto_tsquery`/`ts_rank`, backed by a GIN
  index), fused via Reciprocal Rank Fusion (k=60) down to the final
  top-k=3, joined to originating `knowledge_docs`. The returned score
  is always real cosine similarity (never the RRF fusion score) —
  `app/agent/orchestrator.py`'s routing thresholds depend on that. k=3
  is still the starting value; `tests/evals/test_retrieval_eval.py` is
  the mechanism for tuning it with actual numbers later.
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
- **Routing decision data:** `agent_decisions` now carries
  `total_latency_ms`, `claude_input_tokens`, and `claude_output_tokens`
  per decision (ADR-0010), alongside `model_used`.
  `scripts/cost_report.py` (`docker compose exec api python
  scripts/cost_report.py`) prints the Ollama-vs-Claude comparison
  `project-brief.md` asks for — a report generator, not a live
  dashboard (see Open questions: tracing).
- **Prompt versioning:** each prompt (`app/agent/classify.py`,
  `drafting.py`, `judge.py`) has a `PROMPT_VERSION` constant, recorded
  on `eval_runs.prompt_version` every time the corresponding eval test
  runs (ADR-0010). Not yet recorded on `agent_decisions` itself — no
  column for it there, and not needed yet with one version per prompt.

## Evaluation framework
- **Golden set:** size, how examples were sourced (synthetic vs. real,
  see project-brief.md), how it's kept representative over time.
- **Metrics:** classification accuracy (`test_classification_eval.py`),
  retrieval recall@k and MRR@k (`test_retrieval_eval.py`), RAG
  faithfulness/groundedness (`test_groundedness_eval.py`), triage
  routing accuracy (`test_triage_eval.py`) — each asserts against a
  hardcoded threshold in its own test file, which *is* the regression
  baseline for now (see ADR-0010 for why a separate snapshot-file
  system would be premature at one prompt version each). A run below
  threshold fails its test and blocks CI.
- **Retrieval eval detail:** `tests/evals/retrieval_golden_set.jsonl`
  (12 queries as of Phase 10, up from 8) references expected answers as
  `(doc_title, doc_source, chunk_index)` tuples rather than DB chunk
  ids, since ids aren't stable across re-ingestion — see ADR-0012.
  Recall@3 and MRR@3 are logged as separate `EvalRun` rows
  (`run_type=RETRIEVAL`, distinguished by `details.metric`). Current
  measured result, vector-only vs. hybrid, on the same golden set
  (ADR-0013): **recall@3 = 1.0 / MRR@3 = 1.0 for both** — hybrid search
  (Phase 10) does not show a measurable improvement over pure vector
  search here, even on cases (exact error codes, near-duplicate plan
  names) specifically built to expose vector search's theoretical weak
  spot. Recorded honestly as "not proven on this test," not "doesn't
  work" — this project's corpus and embedding model are both too
  small/too capable, together, to have headroom left for hybrid fusion
  to demonstrate value; a larger, noisier, more realistic knowledge
  base is the condition under which it's expected to actually help.
- **Real-data retrieval eval (Phase 11, ADR-0014):**
  `tests/evals/test_retrieval_eval_real_corpus.py` runs the same
  recall@k/MRR@k measurement against a real, public dataset (MakTek
  Customer Support FAQs, Apache 2.0, deduplicated to 89 genuinely
  unique Q&A pairs — see ADR-0014 for a real data-quality finding: the
  source file repeated 10 questions 12-13x each) instead of the
  synthetic 9-doc corpus. This finally produced non-perfect, headroom-
  bearing numbers: **recall@3 = 0.94, MRR@3 = 0.92** (18 queries), with
  one real, fully-diagnosed miss (a generic "return policy" query
  crowded out of the top-3 by three of the corpus's 17 near-duplicate
  specific-condition return FAQs) and one real rank-2 near-miss. Phase
  12 (contextual retrieval) gets compared against this real baseline
  going forward, not the perfect synthetic one.
- **CI gate:** `.github/workflows/ci.yml`'s `eval-smoke` job runs every
  free eval (no Claude call — `@pytest.mark.costly` marks the one that
  isn't) blocking on every PR; `eval-full` runs everything, including
  the real Claude-calling triage eval, nightly + on manual dispatch
  only, to keep CI's Claude spend bounded.

## Guardrails and safety
- **Input side:** injection detection (`app/guardrails/injection.py`)
  and PII redaction (`app/guardrails/pii.py`) — both pattern-based;
  document if/when either moves to a classifier.
- **Output side:** schema validation via forced Claude tool-use
  (`app/agent/drafting.py`'s `submit_draft` tool + Pydantic
  `DraftOutput`) — a malformed draft escalates the ticket outright
  rather than surfacing a broken reply. Groundedness is a second,
  independent Ollama call (`app/agent/judge.py::assess_groundedness`,
  deterministic temperature) comparing the draft against the retrieved
  context; a failed verdict downgrades `auto_respond` to
  `draft_for_review` rather than just logging the score. See ADR-0009.
- **Red-team set:** how adversarial examples are sourced and grown
  over time (`tests/evals/test_safety_eval.py`), and results of the
  latest run.

## Open questions
Track unresolved design decisions here until they're settled, then
move the resolution into an ADR.
- **Judge reliability:** `tests/evals/test_groundedness_eval.py` checks
  the groundedness judge on two hand-crafted examples (one clearly
  grounded, one clearly hallucinated) — not the full "run the judge
  twice on ~10 examples, confirm stable scores" study
  `project-brief.md`'s review notes call for before trusting a judge
  for regression gating. Still open.
- **Tracing / cost dashboard:** `project-brief.md`'s tech stack names
  Langfuse (or similar) for per-call tracing; `scripts/cost_report.py`
  (ADR-0010) is a deliberately minimal stand-in — a report generator
  run on demand, not a live dashboard with per-call traces. Standing up
  real tracing is a bigger infra lift (a new service, an integration
  point in every model call site) than any pass so far has scoped in.
- **Regression baseline snapshots:** ADR-0010 argues each eval's
  hardcoded threshold already serves as its baseline while there's only
  one prompt version each. Revisit — a committed snapshot file per
  `testing-strategy.md` layer 5 — once prompt iteration actually starts
  happening and "did this PR regress vs. the last known-good version"
  becomes a real question, not a hypothetical one.
