"""
Password hashing and JWT access-token utilities.

Password hashing uses bcrypt directly (via the `bcrypt` package) rather
than a wrapper library, keeping the dependency surface small. Bcrypt
automatically incorporates a random salt per hash and is deliberately
slow, which is the correct property for password storage.

Tokens are signed JWTs (HS256, using `SECRET_KEY`), but a JWT's
signature alone cannot be revoked before it expires. Every token
carries a `jti` claim that must match a non-revoked row in
`auth_sessions` (see `src/models/auth_session.py`) — that row is what
actually gets invalidated on logout or when an account is suspended.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError

from src.core.config import get_settings

_BCRYPT_MAX_BYTES = 72  # bcrypt silently truncates beyond this; reject longer input explicitly.


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password for storage. Never store the plaintext."""
    if len(plain_password.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        raise ValueError("Password exceeds maximum supported length.")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time verification of a plaintext password against its hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed stored hash — treat as a verification failure, not a crash.
        return False


def create_access_token(*, subject: str, jti: str | None = None) -> tuple[str, str, datetime]:
    """Create a signed JWT access token.

    Returns (token, jti, expires_at) so the caller can persist the
    session row that makes the token revocable.
    """
    settings = get_settings()
    jti = jti or uuid.uuid4().hex
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": subject,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token, jti, expires_at


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT access token. Returns None if invalid/expired."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except InvalidTokenError:
        return None
