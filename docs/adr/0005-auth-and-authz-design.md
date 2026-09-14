# ADR-0005: Authentication and authorization design

**Status:** Accepted
**Date:** 2026-09-14

## Context
Phase 2 needs auth and ticket CRUD. `docs/threat-model.md` already flags
two related gaps as "Planned": threat #3 (a user reading another user's
ticket — IDOR) and the fact that authz checks on ticket endpoints don't
exist yet because the endpoints themselves don't exist yet. The schema
from ADR-0004 already has what's needed (`users.hashed_password`,
`users.role`, `tickets.requester_id`, `tickets.assigned_agent_id`), so
this ADR is about the authn mechanism and where authz gets enforced, not
new tables.

## Decision
1. **JWT bearer tokens, signed HS256, via `PyJWT`.** Stateless — no
   session table, no server-side revocation list. Fits a FastAPI
   backend serving a separately-deployed React SPA (the planned
   frontend) better than cookie sessions would. Access tokens are
   short-lived (60 minutes) and carry `sub` (user id) and `role`; no
   refresh-token flow yet — revisit once the frontend needs to keep
   users signed in longer than an hour.
2. **Password hashing via `bcrypt` directly**, not `passlib`. `passlib`
   is in maintenance-only mode with no active releases; wrapping
   `bcrypt.hashpw`/`bcrypt.checkpw` directly in `app/security.py` is one
   less dependency with an unclear maintenance future.
3. **Authz enforced in the router layer**, not the DB layer: a
   `get_current_user` dependency resolves the requester from the token,
   and each ticket endpoint checks `current_user.role in
   ("agent", "admin") or ticket.requester_id == current_user.id` before
   returning or mutating a ticket. `customer`-role users can only see
   and act on tickets they filed; `agent`/`admin` can see and act on any
   ticket. This directly closes threat-model threat #3.
4. **`JWT_SECRET_KEY` is a required env var** (`app/config.py`,
   `.env.example`), read the same way `DATABASE_URL` already is — never
   hardcoded, never defaulted to a real secret (only a clearly-fake
   placeholder in `.env.example`).

## Alternatives considered
- **Server-side sessions (cookie + sessions table)** — simpler to
  revoke, but adds a stateful table and CSRF considerations the JWT
  approach avoids for a token-in-header SPA client. Rejected for now;
  worth revisiting if the frontend ever needs server-forced logout.
- **`passlib[bcrypt]`** — the more commonly-tutorialized choice, but its
  lack of active maintenance made calling `bcrypt` directly the safer
  pick for a project meant to demonstrate current practice.
- **DB row-level security (Postgres RLS) for ticket visibility** —
  would push authz into the database itself, closer to defense-in-depth,
  but adds real operational complexity (session variables per request,
  policy maintenance) that isn't justified yet at this scale. Worth a
  follow-up ADR if the app ever needs to trust less-trusted DB clients.

## Consequences
- No server-side session storage to build or scale.
- Revoking a compromised token before it expires isn't possible without
  adding a denylist — acceptable given the 60-minute expiry, but a real
  gap if this ever needed to handle account compromise response.
- Every new ticket-scoped endpoint has to remember to call the same
  ownership check; if that check logic grows, it should be extracted
  into a shared dependency rather than repeated per-route (already done
  here as a single `ensure_can_view_ticket` helper used by every route
  that takes a `ticket_id`).
