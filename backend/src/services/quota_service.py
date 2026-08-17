"""
Quota enforcement and reporting (Phase 7).

Two independently-configurable limits:
  - Chat limit: max number of ACTIVE chats a user may have at once.
  - Token quota: max tokens (input+output) a user may consume within
    the current renewal window.

Both resolve as: user override > group override > global default (see
`src.core.config.Settings` and the override columns on `User`/`Group`).

Concurrency safety: see `reserve_tokens`/`enforce_chat_limit` docstrings
and ADR 0010. All accounting is derived from persisted rows
(`usage_records`, `quota_reservations`) — never a separately-mutable
counter that could drift from reality or be bypassed by a retry.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, TokenQuotaRenewalPolicy, get_settings
from src.models.group import Group
from src.models.user import User
from src.repositories import quota_repository
from src.services.conversation_errors import ChatLimitExceededError, TokenQuotaExceededError


def get_effective_max_active_chats(user: User, group: Group | None, settings: Settings) -> int:
    if user.max_active_chats_override is not None:
        return user.max_active_chats_override
    if group is not None and group.max_active_chats_override is not None:
        return group.max_active_chats_override
    return settings.default_max_active_chats


def get_effective_token_quota(user: User, group: Group | None, settings: Settings) -> int:
    if user.token_quota_override is not None:
        return user.token_quota_override
    if group is not None and group.token_quota_override is not None:
        return group.token_quota_override
    return settings.default_token_quota


def get_window_start(now: datetime, settings: Settings) -> datetime:
    """The start of the current renewal window, per the configured policy.

    ROLLING_24H: exactly 24 hours before `now` — the window continuously
    slides forward with no fixed reset instant.

    DAILY_RESET_UTC: midnight UTC of the current day — a fixed,
    predictable reset instant shared by everyone.
    """
    if settings.token_quota_renewal_policy == TokenQuotaRenewalPolicy.DAILY_RESET_UTC:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(hours=24)


def get_window_end(now: datetime, window_start: datetime, settings: Settings) -> datetime:
    """When the CURRENT window's capacity is fully available again.

    For DAILY_RESET_UTC this is simply the next midnight UTC — fixed
    and exact. For ROLLING_24H there is no single instant at which
    *all* capacity returns (it continuously trickles back in as old
    usage ages out) — callers wanting a single "renews at" timestamp
    for a rolling window should instead use the oldest in-window
    usage row's timestamp + 24h (see `get_token_quota_status`), which
    is the next moment *any* capacity frees up, not all of it.
    """
    if settings.token_quota_renewal_policy == TokenQuotaRenewalPolicy.DAILY_RESET_UTC:
        return window_start + timedelta(days=1)
    return now + timedelta(hours=24)


async def get_effective_limits_for_user(
    session: AsyncSession, user: User
) -> tuple[int, int]:
    """Returns (max_active_chats, token_quota) for `user`, resolving
    overrides. Loads the user's group fresh (never touches the
    possibly-unloaded `user.group` relationship — see the async-ORM
    caution followed throughout this codebase since Phase 3)."""
    settings = get_settings()
    group = None
    if user.group_id is not None:
        group = await session.get(Group, user.group_id)
    return (
        get_effective_max_active_chats(user, group, settings),
        get_effective_token_quota(user, group, settings),
    )


async def enforce_chat_limit(session: AsyncSession, user: User) -> None:
    """Raise `ChatLimitExceededError` if `user` is already at their
    effective active-chat limit; otherwise return normally.

    Concurrency: acquires a transaction-scoped advisory lock on
    `user.id` before counting, so two simultaneous chat-creation
    requests can't both pass a count-based check that only one of them
    should. Safe to call with no external (model-provider) call
    involved — the lock is released at the same commit that persists
    the newly-created chat, which is exactly when it needs to become
    visible to the next check.
    """
    await quota_repository.acquire_user_lock(session, user.id)
    max_active_chats, _ = await get_effective_limits_for_user(session, user)
    current = await quota_repository.count_active_chats(session, user.id)
    if current >= max_active_chats:
        raise ChatLimitExceededError(limit=max_active_chats, current=current)


@dataclass
class TokenReservation:
    id: uuid.UUID
    estimated_tokens: int


async def reserve_tokens(session: AsyncSession, user: User) -> TokenReservation:
    """Check the user's token quota and, if there's room, create a
    reservation row representing a conservative worst-case estimate for
    one in-flight generation.

    Concurrency: the advisory lock is held only for this function's
    duration (check + insert), NOT across the subsequent model-provider
    call — callers must release the reservation (`release_reservation`)
    once the call finishes, success or failure. Because the reservation
    row is committed before the lock is released, any other concurrent
    request for the same user that acquires the lock next will see it
    in its own usage sum and be correctly blocked if it would exceed
    quota — closing the race a bare "check current usage" would leave
    open. See ADR 0010.
    """
    settings = get_settings()
    await quota_repository.acquire_user_lock(session, user.id)

    _, token_quota = await get_effective_limits_for_user(session, user)
    now = datetime.now(UTC)
    window_start = get_window_start(now, settings)

    used = await quota_repository.sum_usage_tokens_since(session, user.id, window_start)
    reserved = await quota_repository.sum_open_reservations(session, user.id)
    estimate = settings.quota_reservation_estimated_output_tokens

    if used + reserved + estimate > token_quota:
        raise TokenQuotaExceededError(quota=token_quota, used=used + reserved)

    reservation = await quota_repository.create_reservation(
        session, user_id=user.id, estimated_tokens=estimate
    )
    await session.commit()
    return TokenReservation(id=reservation.id, estimated_tokens=estimate)


async def release_reservation(session: AsyncSession, reservation_id: uuid.UUID) -> None:
    """Always called after an in-flight generation finishes, success or
    failure. The reservation's job is done either way — the real charge
    (if any) is the `Usage` row the caller inserts separately on
    success; on failure, nothing further is charged (see ADR 0010's
    documented failed-request policy).

    Commits immediately: on a failure path, the caller may propagate an
    exception without an explicit subsequent commit, and an uncommitted
    delete would be rolled back along with everything else when the
    session closes — permanently leaking the reservation row instead of
    releasing it. Committing here guarantees the release survives
    regardless of what the caller does afterward.
    """
    await quota_repository.delete_reservation(session, reservation_id)
    await session.commit()


@dataclass
class TokenQuotaStatus:
    used_tokens: int
    quota_tokens: int
    percent_used: float
    renewal_policy: TokenQuotaRenewalPolicy
    renews_at: datetime


@dataclass
class ChatLimitStatus:
    active_chats: int
    max_active_chats: int
    percent_used: float


async def get_token_quota_status(session: AsyncSession, user: User) -> TokenQuotaStatus:
    settings = get_settings()
    _, token_quota = await get_effective_limits_for_user(session, user)
    now = datetime.now(UTC)
    window_start = get_window_start(now, settings)

    used = await quota_repository.sum_usage_tokens_since(session, user.id, window_start)
    reserved = await quota_repository.sum_open_reservations(session, user.id)
    total_counted = used + reserved

    if settings.token_quota_renewal_policy == TokenQuotaRenewalPolicy.DAILY_RESET_UTC:
        renews_at = get_window_end(now, window_start, settings)
    else:
        oldest = await quota_repository.earliest_usage_timestamp_since(
            session, user.id, window_start
        )
        # Next moment ANY capacity frees up (see get_window_end docstring);
        # if there's no usage yet, there's nothing to free up — "now".
        renews_at = (oldest + timedelta(hours=24)) if oldest is not None else now

    percent_used = round((total_counted / token_quota) * 100, 2) if token_quota > 0 else 0.0
    return TokenQuotaStatus(
        used_tokens=total_counted,
        quota_tokens=token_quota,
        percent_used=percent_used,
        renewal_policy=settings.token_quota_renewal_policy,
        renews_at=renews_at,
    )


async def get_chat_limit_status(session: AsyncSession, user: User) -> ChatLimitStatus:
    max_active_chats, _ = await get_effective_limits_for_user(session, user)
    current = await quota_repository.count_active_chats(session, user.id)
    percent_used = round((current / max_active_chats) * 100, 2) if max_active_chats > 0 else 0.0
    return ChatLimitStatus(
        active_chats=current, max_active_chats=max_active_chats, percent_used=percent_used
    )
