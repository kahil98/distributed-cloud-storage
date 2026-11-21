from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from security import auth


def test_password_hash_and_signed_bearer_token(monkeypatch):
    monkeypatch.setattr(auth, "SECRET", b"unit-test-secret")
    stored = auth.hash_password("correct horse battery staple")
    assert stored != "correct horse battery staple"
    assert auth.verify_password("correct horse battery staple", stored)
    assert not auth.verify_password("wrong password", stored)
    user = SimpleNamespace(id="user-1", role="user")
    token = auth.issue_token(user)
    claims = auth.current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    assert claims["sub"] == "user-1"
    assert claims["role"] == "user"


def test_expired_and_tampered_tokens_are_rejected(monkeypatch):
    monkeypatch.setattr(auth, "SECRET", b"unit-test-secret")
    user = SimpleNamespace(id="user-1", role="user")
    expired = auth.issue_token(user, ttl=-1)
    for value in (expired, expired + "x"):
        with pytest.raises(HTTPException) as error:
            auth.current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=value))
        assert error.value.status_code == 401
