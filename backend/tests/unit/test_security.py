"""Deterministic checks for password hashing and JWT handling.

No DB, no model calls — pure functions, so this stays in tests/unit
per testing-strategy.md.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import get_settings
from app.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_and_verify_round_trip():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed) is True


def test_verify_rejects_wrong_password():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("wrong-password", hashed) is False


def test_hash_is_not_the_plaintext():
    hashed = hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"


def test_create_and_decode_access_token_round_trip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, role="customer")
    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "customer"


def test_decode_rejects_expired_token():
    settings = get_settings()
    expired_payload = {
        "sub": str(uuid.uuid4()),
        "role": "customer",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    expired_token = jwt.encode(expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)


def test_decode_rejects_tampered_token():
    token = create_access_token(user_id=uuid.uuid4(), role="customer")
    # Flip a character in the middle of the signature, not the last one:
    # the final base64url character of a 32-byte HMAC-SHA256 signature
    # only carries 4 of its 6 bits meaningfully (2 are padding), so some
    # last-character swaps decode to identical bytes and don't actually
    # change the signature — this was genuinely flaky (~1 in 5 runs)
    # before this fix.
    header, payload, signature = token.split(".")
    mid = len(signature) // 2
    flipped_char = "A" if signature[mid] != "A" else "B"
    tampered_signature = signature[:mid] + flipped_char + signature[mid + 1 :]
    tampered = f"{header}.{payload}.{tampered_signature}"
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered)
