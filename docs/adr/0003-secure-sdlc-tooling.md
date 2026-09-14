# ADR-0003: Secure SDLC tooling — branching, CI security scans, pre-commit hooks

**Status:** Accepted
**Date:** 2026-09-13

## Context
"Vibe coding" — prompting an AI assistant into an app with no review
discipline — is exactly what this project exists to demonstrate it's not.
A solo project still needs a real development process, sized to actually
get followed rather than sized for a team that doesn't exist.

## Decision
- All work happens on feature branches; `main` is never committed to
  directly, even solo — every change goes through a PR, self-reviewed and
  merged after CI passes.
- CI (`.github/workflows/ci.yml`) runs on every PR: lint (ruff), SAST
  (bandit), dependency audit (pip-audit), unit tests, the safety/red-team
  eval suite, and integration tests. All of these block merge.
- The eval smoke gate (LLM-as-judge, classification accuracy) runs as a
  non-blocking job until phase 4 lands, then becomes blocking — see the
  CI file comment for why it isn't yet.
- Pre-commit hooks (`detect-secrets`, ruff, bandit, basic hygiene checks)
  catch problems locally before they reach a PR at all.
- A threat model (`docs/threat-model.md`) is maintained and revisited
  whenever a new trust boundary is added.

## Alternatives considered
- **No branch protection, commit straight to main** — faster short-term,
  but produces a git history that doesn't demonstrate any process, which
  defeats the purpose given the target role.
- **Full enterprise-grade tooling** (SBOM generation, container scanning,
  formal threat-model reviews) — rejected as disproportionate to a solo
  portfolio project; would read as over-engineered rather than credible.

## Consequences
- Every merge to `main` has a paper trail: CI results, and a PR
  description, even if self-reviewed.
- Slightly slower to ship a change than pushing directly — intentional.
- The eval smoke gate being non-blocking initially is a known, documented
  gap, not an oversight — revisit this ADR's status once phase 4 lands.
