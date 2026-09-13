# ADR-0001: Record architecture decisions as ADRs

**Status:** Accepted
**Date:** 2026-09-13

## Context
This project exists partly to demonstrate engineering process, not just a
working app. Decisions made ad hoc and forgotten don't show up in an
interview; decisions written down with their reasoning do.

## Decision
Every non-trivial architecture or AI-system decision gets an ADR in
`docs/adr/`, numbered sequentially, using `template.md`. "Non-trivial"
means: it would be expensive to reverse, or a reviewer would reasonably
ask "why did you do it this way."

## Alternatives considered
Just writing it up in the README after the fact — rejected, because
after-the-fact writeups lose the alternatives that were considered and
rejected, which is often the more interesting part in an interview.

## Consequences
Slight overhead per decision. In exchange: a running, dated record of
engineering judgment that can be pointed to directly instead of
reconstructed from memory.
