"""
FastAPI dependencies for authentication and role-based authorization.

This is the single place request-level auth is enforced. Route
handlers depend on `get_current_user` (or the stricter
`require_min_role`/`require_roles`) instead of re-implementing token
parsing or role checks themselves — this is what "prefer role
definitions that do not require hardcoding authorization logic
throughout the application" (Common Instructions / Phase 3 prompt)
means in practice: one shared rank comparison, not scattered
`if role == "..."` checks in every router.

Group-scoped checks (e.g. "a Manager may only act on their own
group") are inherently resource-specific and are implemented at the
call site in the relevant router/service — see `require_self_or_group_manager`
below for the shared helper those call sites use.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import decode_access_token
from src.db.session import get_db
from src.models.enums import ROLE_RANK, Role, UserStatus
from src.models.user import User
from src.repositories import auth_session_repository, user_repository

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user for this request, or 401.

    Validates, in order: token present -> signature/expiry valid ->
    session not revoked -> user still exists -> account still ACTIVE.
    Re-checking status on every request (not just at login) is what
    makes suspending an account take effect immediately instead of
    waiting for the token to expire.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or not credentials.credentials:
        raise credentials_error

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise credentials_error

    jti = payload.get("jti")
    subject = payload.get("sub")
    if not jti or not subject:
        raise credentials_error

    auth_session = await auth_session_repository.get_active_by_jti(session, jti)
    if auth_session is None:
        raise credentials_error

    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise credentials_error from exc

    user = await user_repository.get_by_id(session, user_id)
    if user is None:
        raise credentials_error

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active.",
        )

    request.state.current_user_id = str(user.id)
    request.state.auth_jti = jti
    return user


def require_min_role(min_role: Role):
    """Dependency factory: require the caller's role to rank >= min_role.

    Uses `ROLE_RANK` (see src/models/enums.py) so this is the single
    comparison point for role hierarchy — endpoints never compare role
    names directly.
    """

    async def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK[current_user.role] < ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return _dependency


def require_roles(*allowed_roles: Role):
    """Dependency factory: require the caller's role to be exactly one of `allowed_roles`.

    Use this (instead of `require_min_role`) when a permission is NOT
    naturally hierarchical — e.g. Developer diagnostics access is not
    implied by being an Owner just because Owner outranks Developer in
    general privilege; Owner is explicitly granted both. Prefer
    `require_min_role` where a simple rank threshold is the correct
    model.
    """
    allowed = set(allowed_roles)

    async def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return _dependency


def is_self_or_owner(current_user: User, target_user_id: uuid.UUID) -> bool:
    return current_user.id == target_user_id or current_user.role == Role.OWNER


def can_manage_group(current_user: User, group_id: uuid.UUID | None) -> bool:
    """Whether `current_user` may act on resources scoped to `group_id`.

    Owner: any group (including an ungrouped/None target — Owner has
    global scope). Manager: only their own group, and only if they
    themselves belong to a group. Everyone else: no group-scoped access.
    """
    if current_user.role == Role.OWNER:
        return True
    if current_user.role == Role.MANAGER:
        return current_user.group_id is not None and current_user.group_id == group_id
    return False
