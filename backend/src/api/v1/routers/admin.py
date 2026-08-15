"""
Owner-only administrative endpoints: users, groups, roles, models,
global configuration, audit logs, global usage.

Every route here requires exactly Role.OWNER (the top of the rank
hierarchy — `require_min_role(Role.OWNER)` therefore also correctly
excludes everyone below it).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import require_min_role
from src.core.config import get_settings
from src.db.session import get_db
from src.models.ai_model import AIModel
from src.models.enums import AuditResult, Role
from src.models.group import Group
from src.models.user import User
from src.repositories import (
    audit_log_repository,
    group_repository,
    model_repository,
    usage_repository,
    user_repository,
)
from src.schemas.admin import (
    AuditLogListResponse,
    AuditLogOut,
    GlobalConfigOut,
    GroupCreate,
    GroupOut,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    UserAdminUpdate,
)
from src.schemas.usage import UsageRecordOut, UsageReportResponse
from src.schemas.user import UserSummary

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_min_role(Role.OWNER))],
)


# --- Groups -------------------------------------------------------------

@router.get("/groups", response_model=list[GroupOut])
async def list_groups(session: AsyncSession = Depends(get_db)) -> list[Group]:
    return await group_repository.list_all(session)


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate,
    request: Request,
    current_user: User = Depends(require_min_role(Role.OWNER)),
    session: AsyncSession = Depends(get_db),
) -> Group:
    group = Group(name=payload.name, status=payload.status)
    session.add(group)
    await session.flush()
    await audit_log_repository.create(
        session,
        actor_user_id=current_user.id,
        action="CREATE_GROUP",
        result=AuditResult.SUCCESS,
        target_type="group",
        target_id=str(group.id),
        request_id=getattr(request.state, "request_id", None),
        metadata={"name": group.name},
    )
    await session.commit()
    await session.refresh(group)
    return group


# --- Users (full management) --------------------------------------------

@router.patch("/users/{user_id}", response_model=UserSummary)
async def update_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    request: Request,
    current_user: User = Depends(require_min_role(Role.OWNER)),
    session: AsyncSession = Depends(get_db),
) -> User:
    """The only place a user's role or group may be changed after
    registration — never directly by the affected user (see ADR 0006)."""
    target = await user_repository.get_by_id(session, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if payload.group_id is not None:
        group = await group_repository.get_by_id(session, payload.group_id)
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Group does not exist."
            )

    changes: dict[str, str] = {}
    if payload.role is not None and payload.role != target.role:
        changes["role"] = f"{target.role.value} -> {payload.role.value}"
        target.role = payload.role
    if payload.status is not None and payload.status != target.status:
        changes["status"] = f"{target.status.value} -> {payload.status.value}"
        target.status = payload.status
    if payload.group_id is not None and payload.group_id != target.group_id:
        changes["group_id"] = f"{target.group_id} -> {payload.group_id}"
        target.group_id = payload.group_id

    await audit_log_repository.create(
        session,
        actor_user_id=current_user.id,
        action="ADMIN_UPDATE_USER",
        result=AuditResult.SUCCESS,
        target_type="user",
        target_id=str(target.id),
        request_id=getattr(request.state, "request_id", None),
        metadata=changes,
    )
    await session.commit()
    await session.refresh(target)
    return target


# --- Models ---------------------------------------------------------------

@router.get("/models", response_model=list[ModelOut])
async def list_models(session: AsyncSession = Depends(get_db)) -> list[AIModel]:
    return await model_repository.list_all(session)


@router.post("/models", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelCreate,
    request: Request,
    current_user: User = Depends(require_min_role(Role.OWNER)),
    session: AsyncSession = Depends(get_db),
) -> AIModel:
    if await model_repository.get_by_key(session, payload.model_key) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A model with this key already exists."
        )
    model = AIModel(**payload.model_dump())
    session.add(model)
    await session.flush()
    await audit_log_repository.create(
        session,
        actor_user_id=current_user.id,
        action="CREATE_MODEL",
        result=AuditResult.SUCCESS,
        target_type="model",
        target_id=str(model.id),
        request_id=getattr(request.state, "request_id", None),
        metadata={"model_key": model.model_key},
    )
    await session.commit()
    await session.refresh(model)
    return model


@router.patch("/models/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: uuid.UUID,
    payload: ModelUpdate,
    request: Request,
    current_user: User = Depends(require_min_role(Role.OWNER)),
    session: AsyncSession = Depends(get_db),
) -> AIModel:
    model = await model_repository.get_by_id(session, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found.")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(model, field, value)

    await audit_log_repository.create(
        session,
        actor_user_id=current_user.id,
        action="UPDATE_MODEL",
        result=AuditResult.SUCCESS,
        target_type="model",
        target_id=str(model.id),
        request_id=getattr(request.state, "request_id", None),
        metadata={"fields_changed": list(updates)},
    )
    await session.commit()
    await session.refresh(model)
    return model


# --- Audit logs -------------------------------------------------------------

@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    limit: int = 100, offset: int = 0, session: AsyncSession = Depends(get_db)
) -> AuditLogListResponse:
    entries = await audit_log_repository.list_all(session, limit=limit, offset=offset)
    return AuditLogListResponse(
        entries=[AuditLogOut.model_validate(e) for e in entries], total=len(entries)
    )


# --- Global usage -----------------------------------------------------------

@router.get("/usage", response_model=UsageReportResponse)
async def get_global_usage(
    limit: int = 200, offset: int = 0, session: AsyncSession = Depends(get_db)
) -> UsageReportResponse:
    records = await usage_repository.list_all(session, limit=limit, offset=offset)
    items = [UsageRecordOut.model_validate(r) for r in records]
    return UsageReportResponse(
        records=items,
        total_input_tokens=sum(r.input_tokens for r in records),
        total_output_tokens=sum(r.output_tokens for r in records),
        total_tokens=sum(r.total_tokens for r in records),
    )


# --- Global configuration (non-secret only) ----------------------------

@router.get("/config", response_model=GlobalConfigOut)
async def get_global_config() -> GlobalConfigOut:
    settings = get_settings()
    return GlobalConfigOut(
        app_name=settings.app_name,
        environment=settings.environment.value,
        rate_limit_requests_per_minute=settings.rate_limit_requests_per_minute,
        access_token_expire_minutes=settings.access_token_expire_minutes,
    )
