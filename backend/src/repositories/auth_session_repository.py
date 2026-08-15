"""Data access for the `auth_sessions` table (token revocation)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.auth_session import AuthSession


async def create(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    jti: str,
    expires_at: datetime,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> AuthSession:
    auth_session = AuthSession(
        user_id=user_id,
        jti=jti,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    session.add(auth_session)
    await session.flush()
    return auth_session


async def get_active_by_jti(session: AsyncSession, jti: str) -> AuthSession | None:
    stmt = select(AuthSession).where(AuthSession.jti == jti, AuthSession.revoked_at.is_(None))
    return await session.scalar(stmt)


async def revoke(session: AsyncSession, auth_session: AuthSession) -> None:
    auth_session.revoked_at = datetime.now(UTC)
    await session.flush()


async def revoke_by_jti(session: AsyncSession, jti: str) -> bool:
    auth_session = await get_active_by_jti(session, jti)
    if auth_session is None:
        return False
    await revoke(session, auth_session)
    return True
