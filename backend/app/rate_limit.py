"""Rate limiting for AI-facing endpoints — see ADR-0018 and
threat-model.md item #4 (unbounded requests running up LLM API cost).

Deliberately simple to start, same philosophy as app/guardrails/: an
in-memory fixed-window counter, no new infrastructure. Correct for
this deployment specifically because `docker-compose.yml` runs a
single `api` process (no `--workers`, no replicas) — state living in a
module-level dict is process-wide state here, not an approximation.
"""
import time
from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.dependencies import get_current_user
from app.models import User

_store: dict[str, tuple[float, int]] = {}


def check_rate_limit(
    key: str, max_requests: int, window_seconds: float, *, now: float
) -> tuple[bool, float]:
    """Pure fixed-window check: bump `key`'s counter, resetting the
    window if it's expired. Returns (allowed, retry_after_seconds).
    `now` is passed in (not read from `time.monotonic()` here) so
    tests can drive it with a fake clock deterministically.
    """
    window_start, count = _store.get(key, (now, 0))
    if now - window_start >= window_seconds:
        window_start, count = now, 0

    if count >= max_requests:
        return False, window_seconds - (now - window_start)

    _store[key] = (window_start, count + 1)
    return True, 0.0


def reset_rate_limits() -> None:
    """Test-only: clears all in-memory counters."""
    _store.clear()


def rate_limit(key: str, max_requests: int, window_seconds: float) -> Callable:
    """FastAPI dependency factory — same shape as `require_role` in
    app/dependencies.py. Keyed per authenticated user, not IP: every
    endpoint this protects already requires auth, and per-user is more
    precise than per-IP (shared NAT, proxies, etc.).

    Defined as `async def` on purpose: FastAPI runs a plain `def`
    dependency in a threadpool, where two concurrent requests for the
    same user could race on the shared dict's read-modify-write. An
    `async def` with no `await` inside instead runs directly on the
    single-threaded event loop, making the check-and-increment atomic
    without needing an explicit lock.
    """

    async def _check(current_user: User = Depends(get_current_user)) -> None:
        allowed, retry_after = check_rate_limit(
            f"{key}:{current_user.id}", max_requests, window_seconds, now=time.monotonic()
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded, try again shortly.",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

    return _check
