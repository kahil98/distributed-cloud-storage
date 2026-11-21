from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)
SECRET = os.getenv("JWT_SECRET", os.getenv("INTERNAL_TOKEN", "development-only-change-me")).encode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return base64.urlsafe_b64encode(salt + digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        value = base64.urlsafe_b64decode(encoded.encode())
        salt, expected = value[:16], value[16:]
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def issue_token(user: User, ttl: int = 3600) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user.id, "role": user.role,
                         "exp": int(time.time()) + ttl}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return payload + "." + signature


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None: raise HTTPException(401, "Bearer token required")
    try:
        payload, signature = credentials.credentials.split(".", 1)
        expected = base64.urlsafe_b64encode(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(signature, expected): raise ValueError
        body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if body["exp"] < time.time(): raise ValueError
        return body
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(401, "Invalid or expired bearer token")


def require_admin(claims=Depends(current_user)):
    if claims.get("role") != "admin": raise HTTPException(403, "Administrator role required")
    return claims
