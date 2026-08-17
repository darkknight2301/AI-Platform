"""Pydantic schemas for the Phase 7 quota-status endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from src.core.config import TokenQuotaRenewalPolicy


class TokenQuotaOut(BaseModel):
    used_tokens: int
    quota_tokens: int
    percent_used: float
    renewal_policy: TokenQuotaRenewalPolicy
    renews_at: datetime


class ChatLimitOut(BaseModel):
    active_chats: int
    max_active_chats: int
    percent_used: float


class QuotaStatusResponse(BaseModel):
    token_quota: TokenQuotaOut
    chat_limit: ChatLimitOut
