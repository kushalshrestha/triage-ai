"""Real API + real (test) DB, using the actual local embedding model
(no LLM/hosted call involved, so nothing needs mocking here, per
testing-strategy.md).
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DocChunk, KnowledgeDoc, User, UserRole
from app.security import create_access_token, hash_password

PASSWORD_RESET_DOC = (
    "To reset your password, go to the login page and click 'Forgot password'. "
    "Enter your account email and we'll send a reset link. The link expires "
    "after one hour. If you don't receive the email, check your spam folder "
    "or contact support to have your account manually reset."
)

BILLING_REFUND_DOC = (
    "Refunds for subscription charges are processed within 5-7 business days "
    "back to the original payment method. To request a refund, go to Billing "
    "> Subscription and click 'Request refund', or contact support with your "
    "invoice number if the option isn't available for your plan."
)


def _make_staff_user(db_session: Session, email: str, role: UserRole = UserRole.AGENT) -> str:
    user = User(email=email, hashed_password=hash_password("hunter22222"), role=role)
    db_session.add(user)
    db_session.flush()
    return create_access_token(user_id=user.id, role=user.role.value)


def _register_customer(client: TestClient, email: str) -> str:
    client.post("/auth/register", json={"email": email, "password": "hunter22222"})
    login = client.post("/auth/login", data={"username": email, "password": "hunter22222"})
    return login.json()["access_token"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_customer_cannot_ingest_knowledge_doc(client: TestClient):
    token = _register_customer(client, "not-staff@example.com")
    response = client.post(
        "/knowledge",
        json={"title": "Password reset", "content": PASSWORD_RESET_DOC},
        headers=_auth_header(token),
    )
    assert response.status_code == 403


def test_staff_can_ingest_doc_and_chunks_are_created(client: TestClient, db_session: Session):
    token = _make_staff_user(db_session, "ingest-agent@example.com")
    response = client.post(
        "/knowledge",
        json={"title": "Password reset", "source": "faq", "content": PASSWORD_RESET_DOC},
        headers=_auth_header(token),
    )
    assert response.status_code == 201
    body = response.json()
    doc_id = body["id"]
    assert body["content"] == PASSWORD_RESET_DOC

    chunks = db_session.query(DocChunk).filter_by(knowledge_doc_id=doc_id).all()
    assert len(chunks) >= 1
    assert all(chunk.embedding is not None for chunk in chunks)


def test_search_ranks_relevant_doc_first(client: TestClient, db_session: Session):
    token = _make_staff_user(db_session, "search-agent@example.com")
    client.post(
        "/knowledge",
        json={"title": "Password reset FAQ", "content": PASSWORD_RESET_DOC},
        headers=_auth_header(token),
    )
    client.post(
        "/knowledge",
        json={"title": "Billing refund FAQ", "content": BILLING_REFUND_DOC},
        headers=_auth_header(token),
    )

    response = client.get(
        "/knowledge/search",
        params={"q": "I forgot my password and need to reset it", "k": 3},
        headers=_auth_header(token),
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) >= 1
    assert results[0]["knowledge_doc_title"] == "Password reset FAQ"


def test_search_is_available_to_customers_too(client: TestClient, db_session: Session):
    staff_token = _make_staff_user(db_session, "seed-agent@example.com")
    client.post(
        "/knowledge",
        json={"title": "Billing refund FAQ", "content": BILLING_REFUND_DOC},
        headers=_auth_header(staff_token),
    )

    customer_token = _register_customer(client, "searching-customer@example.com")
    response = client.get(
        "/knowledge/search", params={"q": "refund"}, headers=_auth_header(customer_token)
    )
    assert response.status_code == 200


def test_list_includes_content(client: TestClient, db_session: Session):
    token = _make_staff_user(db_session, "list-agent@example.com")
    client.post(
        "/knowledge",
        json={"title": "Billing refund FAQ", "content": BILLING_REFUND_DOC},
        headers=_auth_header(token),
    )

    response = client.get("/knowledge", headers=_auth_header(token))
    assert response.status_code == 200
    doc = next(d for d in response.json() if d["title"] == "Billing refund FAQ")
    assert doc["content"] == BILLING_REFUND_DOC


def test_customer_cannot_delete_knowledge_doc(client: TestClient, db_session: Session):
    staff_token = _make_staff_user(db_session, "delete-owner-agent@example.com")
    created = client.post(
        "/knowledge",
        json={"title": "Password reset", "content": PASSWORD_RESET_DOC},
        headers=_auth_header(staff_token),
    ).json()

    customer_token = _register_customer(client, "cannot-delete@example.com")
    response = client.delete(f"/knowledge/{created['id']}", headers=_auth_header(customer_token))
    assert response.status_code == 403


def test_staff_can_delete_knowledge_doc_and_chunks_go_with_it(
    client: TestClient, db_session: Session
):
    token = _make_staff_user(db_session, "delete-agent@example.com")
    created = client.post(
        "/knowledge",
        json={"title": "Password reset", "content": PASSWORD_RESET_DOC},
        headers=_auth_header(token),
    ).json()

    response = client.delete(f"/knowledge/{created['id']}", headers=_auth_header(token))
    assert response.status_code == 204

    assert db_session.get(KnowledgeDoc, created["id"]) is None
    remaining_chunks = db_session.query(DocChunk).filter_by(knowledge_doc_id=created["id"]).all()
    assert remaining_chunks == []

    list_response = client.get("/knowledge", headers=_auth_header(token))
    assert all(d["id"] != created["id"] for d in list_response.json())


def test_deleting_unknown_knowledge_doc_returns_404(client: TestClient, db_session: Session):
    token = _make_staff_user(db_session, "delete-404-agent@example.com")
    response = client.delete(
        "/knowledge/00000000-0000-0000-0000-000000000000", headers=_auth_header(token)
    )
    assert response.status_code == 404
