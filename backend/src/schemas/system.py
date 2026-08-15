"""Pydantic schemas for developer-facing system/diagnostics endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.models.enums import ModelCategory


class LogEntryOut(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str


class RecentLogsResponse(BaseModel):
    entries: list[LogEntryOut]


class ModelStatusOut(BaseModel):
    id: uuid.UUID
    model_key: str
    display_name: str
    category: ModelCategory
    provider: str
    version: str
    is_enabled: bool

    model_config = {"from_attributes": True}


class ModelStatusResponse(BaseModel):
    models: list[ModelStatusOut]


class DiagnosticsResponse(BaseModel):
    environment: str
    database_reachable: bool
    server_time: datetime
    uptime_seconds: float


class PerformanceResponse(BaseModel):
    total_requests: int
    requests_by_status_class: dict[str, int]
    average_response_time_ms: float
    uptime_seconds: float
