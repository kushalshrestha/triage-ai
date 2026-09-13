"""Integration tests hit the real API + real (test) DB.

The LLM call itself gets mocked/stubbed here so these stay fast and
non-flaky — this layer verifies plumbing (persistence, status codes,
routing), not model quality. Model quality lives in tests/evals/.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.skip(reason="Wire up once the tickets router + test DB fixture exist")
def test_create_ticket_persists_and_returns_id():
    response = client.post("/tickets", json={"subject": "Login broken", "body": "..."})
    assert response.status_code == 201
    assert "id" in response.json()
