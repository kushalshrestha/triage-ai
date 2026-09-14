# ADR-0006: Frontend architecture and token storage

**Status:** Accepted
**Date:** 2026-09-14

## Context
`project-brief.md` already settled the frontend framework (React/Vite),
and `docker-compose.yml` already had an empty `frontend` service block
anticipating it. This ADR covers what wasn't already decided: how much
structure the app needs for a first, customer-only pass (login,
register, ticket list, ticket detail with comments), and where the
JWT from ADR-0005 lives once it's in the browser.

## Decision
1. **Vite + React + TypeScript, no UI component library.** Four routes,
   hand-written CSS in one stylesheet. A design system would be
   over-engineering for this scope; TypeScript is worth it to keep the
   API contract (types mirroring `backend/app/schemas/`) explicit as
   the backend evolves.
2. **`react-router-dom`** for routing, with a `RequireAuth` wrapper
   redirecting unauthenticated requests to `/login`.
3. **JWT stored in `localStorage`**, loaded into a small `AuthContext`
   on app start. Known tradeoff: unlike an httpOnly cookie,
   `localStorage` is readable by any script that gets injected via XSS.
   Accepted here because ADR-0005 already made access tokens
   short-lived (60 minutes) specifically to bound that kind of blast
   radius, and there's no refresh token in play to make a stolen token
   valuable for longer. Revisit if this ever needs to survive an XSS
   finding in a real security review, or if a refresh-token flow gets
   added later.
4. **API base URL via `VITE_API_BASE_URL`**, injected as a container
   environment variable in `docker-compose.yml` rather than a
   `frontend/.env` file — Vite treats already-set process env vars as
   higher priority than `.env` files, so this needs no extra file. Set
   to `http://localhost:8000` because the *browser*, not the frontend
   container, makes the API calls, so it needs the host-published port.

## Alternatives considered
- **httpOnly cookie for the token** — better XSS resistance, but
  requires the API to set/manage the cookie and adds CSRF protection
  work that a token-in-header SPA doesn't need. Deferred; worth
  revisiting alongside a refresh-token flow.
- **A UI library (MUI, Chakra, etc.)** — faster to make it look
  polished, but adds a dependency and a design-system-to-learn for a
  four-route app. Rejected for now; can be layered in later without
  restructuring the routes or data flow.
- **OpenAPI-generated TS types** — would keep frontend/backend types
  perfectly in sync automatically, but is more tooling than a two-page
  app justifies yet. Hand-mirrored types in `src/api/types.ts` for now;
  revisit if the schema surface grows enough that drift becomes a real
  problem.

## Consequences
- Every new backend response shape needs its TS type hand-updated in
  `src/api/types.ts` — an explicit, trackable cost given no codegen.
- A future refresh-token or cookie-based auth change touches both the
  backend (ADR-0005) and `AuthContext.tsx` together.
- No design-system lock-in; a UI library can be added later purely
  additively.
