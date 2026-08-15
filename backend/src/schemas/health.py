"""Pydantic schemas for the health check endpoint."""
from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str
