"""
Model listing for any authenticated user (Phase 8).

Distinct from `GET /api/v1/system/models` (Developer+, includes
disabled models — operational visibility) and `GET /api/v1/admin/models`
(Owner, full management). This endpoint exists because the chat
frontend's model selector needs SOME way for an ordinary `Role.USER`
to discover which models they may create a chat against — no such
endpoint existed before Phase 8. Returns only enabled models, and only
the fields relevant to selection (no `config_metadata`, which may
contain operational detail not meant for end users).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.db.session import get_db
from src.models.ai_model import AIModel
from src.models.user import User
from src.repositories import model_repository
from src.schemas.system import ModelStatusOut, ModelStatusResponse

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelStatusResponse)
async def list_available_models(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ModelStatusResponse:
    models: list[AIModel] = await model_repository.list_all(session, enabled_only=True)
    return ModelStatusResponse(models=[ModelStatusOut.model_validate(m) for m in models])
