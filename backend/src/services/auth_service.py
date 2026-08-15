"""
Authentication business logic: registration, login, logout.

Raises `fastapi.HTTPException` directly rather than a separate
exception-translation layer — a deliberate, small-scale pragmatic
choice (see Common Instructions: "avoid unnecessary enterprise
patterns") appropriate for a service this size. Every
success/failure/denial path writes an audit log entry.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, hash_password, verify_password
from src.models.enums import AuditResult, Role, UserStatus
from src.models.user import User
from src.repositories import (
    audit_log_repository,
    auth_session_repository,
    group_repository,
    user_repository,
)
from src.schemas.auth import LoginRequest, RegisterRequest


async def register_user(
    session: AsyncSession, data: RegisterRequest, *, request_id: str | None
) -> User:
    """Create a new pending account.

    Group-assignment policy (see ADR 0006): a registrant may request to
    join an existing, ACTIVE group, but this only associates them with
    that group for a manager to review — it never grants any role.
    Every self-registered account is created with `Role.USER`,
    `UserStatus.PENDING`; there is no field on `RegisterRequest` a
    client can use to influence role, so this isn't just a default —
    it's structurally the only outcome.
    """
    if await user_repository.username_or_email_taken(session, data.username, data.email):
        await audit_log_repository.create(
            session,
            actor_user_id=None,
            action="REGISTER",
            result=AuditResult.FAILURE,
            target_type="user",
            target_id=data.username,
            request_id=request_id,
            metadata={"reason": "username_or_email_taken"},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered.",
        )

    if data.group_id is not None:
        group = await group_repository.get_active_by_id(session, data.group_id)
        if group is None:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Requested group does not exist or is not active.",
            )

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        status=UserStatus.PENDING,
        role=Role.USER,
        group_id=data.group_id,
    )
    session.add(user)
    await session.flush()

    await audit_log_repository.create(
        session,
        actor_user_id=user.id,
        action="REGISTER",
        result=AuditResult.SUCCESS,
        target_type="user",
        target_id=str(user.id),
        request_id=request_id,
        metadata={"requested_group_id": str(data.group_id) if data.group_id else None},
    )
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate(
    session: AsyncSession,
    data: LoginRequest,
    *,
    request_id: str | None,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[User, str, datetime]:
    """Verify credentials + account status, and issue an access token.

    Returns (user, access_token, expires_at_isoformat-ready-datetime).
    """
    user = await user_repository.get_by_username_or_email(session, data.username_or_email)

    if user is None or not verify_password(data.password, user.password_hash):
        await audit_log_repository.create(
            session,
            actor_user_id=user.id if user else None,
            action="LOGIN",
            result=AuditResult.FAILURE,
            target_type="user",
            target_id=(str(user.id) if user else data.username_or_email),
            request_id=request_id,
            metadata={"reason": "invalid_credentials"},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password.",
        )

    if user.status != UserStatus.ACTIVE:
        await audit_log_repository.create(
            session,
            actor_user_id=user.id,
            action="LOGIN",
            result=AuditResult.DENIED,
            target_type="user",
            target_id=str(user.id),
            request_id=request_id,
            metadata={"reason": "account_not_active", "status": user.status.value},
        )
        await session.commit()
        detail = {
            UserStatus.PENDING: "Account is pending manager approval.",
            UserStatus.SUSPENDED: "Account has been suspended.",
            UserStatus.INACTIVE: "Account is inactive.",
        }.get(user.status, "Account is not active.")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    token, jti, expires_at = create_access_token(subject=str(user.id))
    await auth_session_repository.create(
        session,
        user_id=user.id,
        jti=jti,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    user.last_login_at = datetime.now(UTC)

    await audit_log_repository.create(
        session,
        actor_user_id=user.id,
        action="LOGIN",
        result=AuditResult.SUCCESS,
        target_type="user",
        target_id=str(user.id),
        request_id=request_id,
    )
    await session.commit()
    await session.refresh(user)
    return user, token, expires_at


async def logout(
    session: AsyncSession, *, user_id: uuid.UUID, jti: str, request_id: str | None
) -> None:
    revoked = await auth_session_repository.revoke_by_jti(session, jti)
    await audit_log_repository.create(
        session,
        actor_user_id=user_id,
        action="LOGOUT",
        result=AuditResult.SUCCESS if revoked else AuditResult.FAILURE,
        target_type="user",
        target_id=str(user_id),
        request_id=request_id,
    )
    await session.commit()
