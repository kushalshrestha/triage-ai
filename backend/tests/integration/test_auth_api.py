"""Real API + real (test) DB, per testing-strategy.md's integration layer.

No LLM involved here, so nothing needs mocking — these exercise the
actual register/login/me plumbing end to end.
"""
from fastapi.testclient import TestClient


def test_register_then_login_then_me(client: TestClient):
    register_response = client.post(
        "/auth/register", json={"email": "new-user@example.com", "password": "hunter22222"}
    )
    assert register_response.status_code == 201
    body = register_response.json()
    assert body["email"] == "new-user@example.com"
    assert body["role"] == "customer"

    login_response = client.post(
        "/auth/login", data={"username": "new-user@example.com", "password": "hunter22222"}
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "new-user@example.com"


def test_register_duplicate_email_conflicts(client: TestClient):
    payload = {"email": "dupe@example.com", "password": "hunter22222"}
    first = client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = client.post("/auth/register", json=payload)
    assert second.status_code == 409


def test_login_wrong_password_rejected(client: TestClient):
    client.post("/auth/register", json={"email": "wrongpw@example.com", "password": "hunter22222"})
    response = client.post(
        "/auth/login", data={"username": "wrongpw@example.com", "password": "not-the-password"}
    )
    assert response.status_code == 401


def test_me_without_token_rejected(client: TestClient):
    response = client.get("/auth/me")
    assert response.status_code == 401
