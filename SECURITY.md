# Security practices

## Scope
This is a portfolio project, not a production service handling real
customer data. The practices below are sized for that — real engineering
discipline, without enterprise process that wouldn't be credible for a
solo project.

## Secrets
- Never committed. `.env` is gitignored; `.env.example` documents required
  variables without values.
- `detect-secrets` runs as a pre-commit hook against every commit.

## Dependencies
- Pinned versions in `requirements.txt` / `requirements-dev.txt`.
- `pip-audit` runs in CI on every PR; a known vulnerability fails the build.

## Static analysis
- `bandit` (SAST) runs against `app/` in CI, excluding `tests/`.
- `ruff` lint runs in CI; a failing lint blocks merge.

## Access control
- Ticket data is scoped per user — every ticket endpoint must verify the
  requesting user owns (or is authorized on) the ticket before returning
  or modifying it. See `docs/threat-model.md` item #3.

## AI-specific controls
- Input guardrails (injection detection, PII redaction) run before any
  ticket text reaches a model call or a log line.
- Output guardrails validate structure and check groundedness against
  retrieved context before a response reaches a user.
- See `docs/ai-architecture.md` and `docs/threat-model.md` for the full
  design and current implementation status of each control.

## Reporting
Solo project — no formal disclosure process. If this were to accept
outside contributions, this section would define one.
