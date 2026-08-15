"""Pydantic schemas for usage reporting endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class UsageRecordOut(BaseModel):
    id: uuid.UUID
    chat_id: uuid.UUID | None
    message_id: uuid.UUID | None
    model_id: uuid.UUID
    input_tokens: int
    output_tokens: int
    total_tokens: int
    timestamp: datetime

    model_config = {"from_attributes": True}


class UsageReportResponse(BaseModel):
    records: list[UsageRecordOut]
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
