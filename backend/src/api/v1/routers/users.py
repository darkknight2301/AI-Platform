"""
User-facing and Manager-facing endpoints.

Authorization here is the concrete implementation of the Phase 3
security requirements:
  - "User A cannot access User B"          -> get_user
  - "Manager A cannot manage Group B"      -> list_users / approve / reject
  - "Unauthenticated users cannot call protected APIs" -> get_current_user
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import can_manage_group, get_current_user, require_min_role
from src.db.session import get_db
from src.models.enums import Role, UserStatus
from src.models.user import User
from src.repositories import usage_repository
from src.schemas.quota import ChatLimitOut, QuotaStatusResponse, TokenQuotaOut
from src.schemas.usage import UsageRecordOut, UsageReportResponse
from src.schemas.user import ApprovalActionResponse, UserListResponse, UserSummary
from src.services import quota_service, user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserSummary)
async def get_my_profile(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/me/usage", response_model=UsageReportResponse)
async def get_my_usage(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UsageReportResponse:
    """A User may always view their own usage — no elevated role required."""
    records = await usage_repository.list_by_user(session, current_user.id)
    return _to_usage_report(records)


@router.get("/me/quota", response_model=QuotaStatusResponse)
async def get_my_quota(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> QuotaStatusResponse:
    """Enough for the frontend to show '62%', '62,000 / 100,000', and a
    renewal time — see src/services/quota_service.py and ADR 0010."""
    return await _to_quota_status(session, current_user)


@router.get("", response_model=UserListResponse)
async def list_users(
    status_filter: UserStatus | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """Owner: all users. Manager: only users in their own group.

    Anyone else gets 403 from `user_service.list_users_for_requester`.
    """
    users = await user_service.list_users_for_requester(
        session, requester=current_user, status_filter=status_filter
    )
    return UserListResponse(
        users=[UserSummary.model_validate(u) for u in users], total=len(users)
    )


@router.get("/groups/{group_id}/usage", response_model=UsageReportResponse)
async def get_group_usage(
    group_id: uuid.UUID,
    current_user: User = Depends(require_min_role(Role.MANAGER)),
    session: AsyncSession = Depends(get_db),
) -> UsageReportResponse:
    """Manager: usage for their own group only. Owner: any group.

    Registered ahead of `/{user_id}` — a static-looking path segment
    ("groups") must not be shadowed by the dynamic `{user_id}` route.
    """
    if not can_manage_group(current_user, group_id):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view usage for this group.",
        )
    records = await usage_repository.list_by_group(session, group_id)
    return _to_usage_report(records)


@router.get("/{user_id}", response_model=UserSummary)
async def get_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> User:
    return await user_service.get_user_for_requester(
        session, requester=current_user, target_user_id=user_id
    )


@router.post("/{user_id}/approve", response_model=ApprovalActionResponse)
async def approve_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_min_role(Role.MANAGER)),
    session: AsyncSession = Depends(get_db),
) -> ApprovalActionResponse:
    request_id = getattr(request.state, "request_id", None)
    target = await user_service.approve_user(
        session, requester=current_user, target_user_id=user_id, request_id=request_id
    )
    return ApprovalActionResponse(
        id=target.id, status=target.status, detail="User approved and activated."
    )


@router.post("/{user_id}/reject", response_model=ApprovalActionResponse)
async def reject_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_min_role(Role.MANAGER)),
    session: AsyncSession = Depends(get_db),
) -> ApprovalActionResponse:
    request_id = getattr(request.state, "request_id", None)
    target = await user_service.reject_user(
        session, requester=current_user, target_user_id=user_id, request_id=request_id
    )
    return ApprovalActionResponse(
        id=target.id, status=target.status, detail="User rejected."
    )


@router.get("/{user_id}/quota", response_model=QuotaStatusResponse)
async def get_user_quota(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> QuotaStatusResponse:
    """Self, Owner, or a Manager of the target's own group — same
    authorization as `get_user` (Phase 3's `user_service`)."""
    target = await user_service.get_user_for_requester(
        session, requester=current_user, target_user_id=user_id
    )
    return await _to_quota_status(session, target)


async def _to_quota_status(session: AsyncSession, user: User) -> QuotaStatusResponse:
    token_status = await quota_service.get_token_quota_status(session, user)
    chat_status = await quota_service.get_chat_limit_status(session, user)
    return QuotaStatusResponse(
        token_quota=TokenQuotaOut(
            used_tokens=token_status.used_tokens,
            quota_tokens=token_status.quota_tokens,
            percent_used=token_status.percent_used,
            renewal_policy=token_status.renewal_policy,
            renews_at=token_status.renews_at,
        ),
        chat_limit=ChatLimitOut(
            active_chats=chat_status.active_chats,
            max_active_chats=chat_status.max_active_chats,
            percent_used=chat_status.percent_used,
        ),
    )


def _to_usage_report(records: list) -> UsageReportResponse:
    items = [UsageRecordOut.model_validate(r) for r in records]
    return UsageReportResponse(
        records=items,
        total_input_tokens=sum(r.input_tokens for r in records),
        total_output_tokens=sum(r.output_tokens for r in records),
        total_tokens=sum(r.total_tokens for r in records),
    )
