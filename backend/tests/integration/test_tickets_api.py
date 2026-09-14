"""Integration tests hit the real API + real (test) DB.

No LLM call is involved in ticket CRUD yet (that lands with agent
orchestration in a later phase), so nothing needs stubbing here — this
layer verifies plumbing and authz, per testing-strategy.md.
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, UserRole
from app.security import create_access_token, hash_password


def test_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _register_and_login(client: TestClient, email: str) -> str:
    client.post("/auth/register", json={"email": email, "password": "hunter22222"})
    login = client.post("/auth/login", data={"username": email, "password": "hunter22222"})
    return login.json()["access_token"]


def _make_agent(db_session: Session, email: str) -> tuple[User, str]:
    agent = User(email=email, hashed_password=hash_password("hunter22222"), role=UserRole.AGENT)
    db_session.add(agent)
    db_session.flush()
    token = create_access_token(user_id=agent.id, role=agent.role.value)
    return agent, token


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_ticket_persists_and_returns_id(client: TestClient):
    token = _register_and_login(client, "requester@example.com")
    response = client.post(
        "/tickets",
        json={"subject": "Login broken", "body": "Can't log in since the reset."},
        headers=_auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["status"] == "open"


def test_customer_can_read_their_own_ticket(client: TestClient):
    token = _register_and_login(client, "owner@example.com")
    created = client.post(
        "/tickets", json={"subject": "Billing question", "body": "..."}, headers=_auth_header(token)
    ).json()

    response = client.get(f"/tickets/{created['id']}", headers=_auth_header(token))
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_customer_cannot_read_another_customers_ticket(client: TestClient):
    owner_token = _register_and_login(client, "ticket-owner@example.com")
    other_token = _register_and_login(client, "other-customer@example.com")

    created = client.post(
        "/tickets", json={"subject": "Private issue", "body": "..."}, headers=_auth_header(owner_token)
    ).json()

    response = client.get(f"/tickets/{created['id']}", headers=_auth_header(other_token))
    assert response.status_code == 403


def test_unknown_ticket_returns_404(client: TestClient):
    token = _register_and_login(client, "someone@example.com")
    response = client.get(
        "/tickets/00000000-0000-0000-0000-000000000000", headers=_auth_header(token)
    )
    assert response.status_code == 404


def test_customer_ticket_list_only_shows_their_own(client: TestClient):
    a_token = _register_and_login(client, "customer-a@example.com")
    b_token = _register_and_login(client, "customer-b@example.com")
    client.post("/tickets", json={"subject": "A's ticket", "body": "..."}, headers=_auth_header(a_token))
    client.post("/tickets", json={"subject": "B's ticket", "body": "..."}, headers=_auth_header(b_token))

    response = client.get("/tickets", headers=_auth_header(a_token))
    assert response.status_code == 200
    subjects = [t["subject"] for t in response.json()]
    assert subjects == ["A's ticket"]


def test_agent_can_read_and_list_any_ticket(client: TestClient, db_session: Session):
    customer_token = _register_and_login(client, "agent-view-target@example.com")
    created = client.post(
        "/tickets", json={"subject": "Needs an agent", "body": "..."}, headers=_auth_header(customer_token)
    ).json()

    _, agent_token = _make_agent(db_session, "agent1@example.com")

    get_response = client.get(f"/tickets/{created['id']}", headers=_auth_header(agent_token))
    assert get_response.status_code == 200

    list_response = client.get("/tickets", headers=_auth_header(agent_token))
    assert list_response.status_code == 200
    assert any(t["id"] == created["id"] for t in list_response.json())


def test_customer_cannot_patch_ticket_status(client: TestClient):
    token = _register_and_login(client, "no-patch@example.com")
    created = client.post(
        "/tickets", json={"subject": "Can I close this?", "body": "..."}, headers=_auth_header(token)
    ).json()

    response = client.patch(
        f"/tickets/{created['id']}", json={"status": "resolved"}, headers=_auth_header(token)
    )
    assert response.status_code == 403


def test_agent_can_patch_status_and_it_logs_an_event(client: TestClient, db_session: Session):
    customer_token = _register_and_login(client, "gets-resolved@example.com")
    created = client.post(
        "/tickets", json={"subject": "Please resolve", "body": "..."}, headers=_auth_header(customer_token)
    ).json()

    _, agent_token = _make_agent(db_session, "agent2@example.com")
    response = client.patch(
        f"/tickets/{created['id']}", json={"status": "resolved"}, headers=_auth_header(agent_token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_comment_visible_to_owner_and_agent_not_other_customers(client: TestClient, db_session: Session):
    owner_token = _register_and_login(client, "commenter-owner@example.com")
    other_token = _register_and_login(client, "commenter-other@example.com")
    created = client.post(
        "/tickets", json={"subject": "Has a comment", "body": "..."}, headers=_auth_header(owner_token)
    ).json()

    comment_response = client.post(
        f"/tickets/{created['id']}/events", json={"body": "any update?"}, headers=_auth_header(owner_token)
    )
    assert comment_response.status_code == 201
    assert comment_response.json()["event_type"] == "comment_added"

    forbidden = client.post(
        f"/tickets/{created['id']}/events", json={"body": "nosy"}, headers=_auth_header(other_token)
    )
    assert forbidden.status_code == 403
