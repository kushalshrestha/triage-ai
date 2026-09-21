"""Rate limiting on AI-facing endpoints — see ADR-0018.

Uses the real configured limits (`Settings.triage_rate_limit_per_minute`
etc.) rather than monkeypatching them smaller: the `rate_limit(...)`
dependency factory is evaluated once at router-import time (same as
`require_role`), so the limit values are baked into the app at startup
and can't be swapped per-test.
"""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent import orchestrator
from app.config import get_settings
from app.models import User, UserRole
from app.rate_limit import reset_rate_limits
from app.security import create_access_token, hash_password


def setup_function():
    reset_rate_limits()


def _make_staff_user(db_session: Session, email: str) -> str:
    user = User(email=email, hashed_password=hash_password("hunter22222"), role=UserRole.AGENT)
    db_session.add(user)
    db_session.flush()
    return create_access_token(user_id=user.id, role=user.role.value)


def _register_customer(client: TestClient, email: str) -> str:
    client.post("/auth/register", json={"email": email, "password": "hunter22222"})
    login = client.post("/auth/login", data={"username": email, "password": "hunter22222"})
    return login.json()["access_token"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_triage_endpoint_returns_429_after_exceeding_the_limit(
    client: TestClient, db_session: Session, monkeypatch
):
    monkeypatch.setattr(orchestrator, "classify_ticket", MagicMock(return_value="bug"))
    monkeypatch.setattr(orchestrator, "generate_draft", MagicMock())

    staff_token = _make_staff_user(db_session, "rate-limit-triage-agent@example.com")
    customer_token = _register_customer(client, "rate-limit-customer@example.com")

    limit = get_settings().triage_rate_limit_per_minute
    responses = []
    for i in range(limit + 1):
        ticket = client.post(
            "/tickets",
            json={"subject": f"Ticket {i}", "body": "Not covered by anything in the KB."},
            headers=_auth_header(customer_token),
        ).json()
        responses.append(
            client.post(f"/tickets/{ticket['id']}/triage", headers=_auth_header(staff_token))
        )

    assert [r.status_code for r in responses[:limit]] == [201] * limit
    last = responses[limit]
    assert last.status_code == 429
    assert "Retry-After" in last.headers


def test_triage_rate_limit_is_scoped_per_user(client: TestClient, db_session: Session, monkeypatch):
    monkeypatch.setattr(orchestrator, "classify_ticket", MagicMock(return_value="bug"))
    monkeypatch.setattr(orchestrator, "generate_draft", MagicMock())

    limit = get_settings().triage_rate_limit_per_minute
    staff_a = _make_staff_user(db_session, "rate-limit-agent-a@example.com")
    staff_b = _make_staff_user(db_session, "rate-limit-agent-b@example.com")
    customer_token = _register_customer(client, "rate-limit-customer-2@example.com")

    for i in range(limit):
        ticket = client.post(
            "/tickets",
            json={"subject": f"A ticket {i}", "body": "Not covered by anything in the KB."},
            headers=_auth_header(customer_token),
        ).json()
        response = client.post(f"/tickets/{ticket['id']}/triage", headers=_auth_header(staff_a))
        assert response.status_code == 201

    # staff_a is now at its limit; a different user is unaffected.
    ticket = client.post(
        "/tickets",
        json={"subject": "B ticket", "body": "Not covered by anything in the KB."},
        headers=_auth_header(customer_token),
    ).json()
    response = client.post(f"/tickets/{ticket['id']}/triage", headers=_auth_header(staff_b))
    assert response.status_code == 201


def test_knowledge_search_endpoint_returns_429_after_exceeding_the_limit(
    client: TestClient, db_session: Session
):
    customer_token = _register_customer(client, "rate-limit-search-customer@example.com")

    limit = get_settings().knowledge_search_rate_limit_per_minute
    statuses = [
        client.get(
            "/knowledge/search", params={"q": "anything"}, headers=_auth_header(customer_token)
        ).status_code
        for _ in range(limit + 1)
    ]

    assert statuses[:limit] == [200] * limit
    assert statuses[limit] == 429
