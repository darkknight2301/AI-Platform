"""
User-management business logic: profile access and the manager
approval workflow (Pending -> Active / Pending -> rejected).
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import can_manage_group, is_self_or_owner
from src.models.enums import AuditResult, Role, UserStatus
from src.models.user import User
from src.repositories import audit_log_repository, user_repository


async def get_user_for_requester(
    session: AsyncSession, *, requester: User, target_user_id: uuid.UUID
) -> User:
    """Fetch a user profile, enforcing: self, Owner, or Manager-of-same-group.

    This is the exact enforcement point behind the "User A cannot
    access User B" / "Manager A cannot manage Group B" security
    requirements.
    """
    target = await user_repository.get_by_id(session, target_user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if is_self_or_owner(requester, target.id):
        return target
    if requester.role == Role.MANAGER and can_manage_group(requester, target.group_id):
        return target

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to view this user.",
    )


async def list_users_for_requester(
    session: AsyncSession, *, requester: User, status_filter: UserStatus | None
) -> list[User]:
    """List users visible to the requester.

    Owner: every user (optionally filtered by status). Manager: only
    users in the manager's own group. No other role may list users —
    Developer's diagnostics access does not extend to user PII (see
    Phase 3 requirement: "Do not automatically grant unrestricted
    private [...] access").
    """
    if requester.role == Role.OWNER:
        return await user_repository.list_all(session, status=status_filter)
    if requester.role == Role.MANAGER:
        if requester.group_id is None:
            return []
        return await user_repository.list_by_group(
            session, requester.group_id, status=status_filter
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to list users.",
    )


async def _authorize_approval_action(
    session: AsyncSession, *, requester: User, target_user_id: uuid.UUID
) -> User:
    target = await user_repository.get_by_id(session, target_user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if target.status != UserStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not pending approval.",
        )

    if requester.role == Role.OWNER:
        return target
    if requester.role == Role.MANAGER and can_manage_group(requester, target.group_id):
        return target

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to approve or reject this user.",
    )


async def approve_user(
    session: AsyncSession, *, requester: User, target_user_id: uuid.UUID, request_id: str | None
) -> User:
    target = await _authorize_approval_action(
        session, requester=requester, target_user_id=target_user_id
    )
    target.status = UserStatus.ACTIVE
    await audit_log_repository.create(
        session,
        actor_user_id=requester.id,
        action="APPROVE_USER",
        result=AuditResult.SUCCESS,
        target_type="user",
        target_id=str(target.id),
        request_id=request_id,
    )
    await session.commit()
    await session.refresh(target)
    return target


async def reject_user(
    session: AsyncSession, *, requester: User, target_user_id: uuid.UUID, request_id: str | None
) -> User:
    target = await _authorize_approval_action(
        session, requester=requester, target_user_id=target_user_id
    )
    target.status = UserStatus.INACTIVE
    await audit_log_repository.create(
        session,
        actor_user_id=requester.id,
        action="REJECT_USER",
        result=AuditResult.SUCCESS,
        target_type="user",
        target_id=str(target.id),
        request_id=request_id,
    )
    await session.commit()
    await session.refresh(target)
    return target
