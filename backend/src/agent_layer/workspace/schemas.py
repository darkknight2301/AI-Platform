"""API-facing schemas for the workspace/Web IDE subsystem."""
from __future__ import annotations

import uuid

from pydantic import BaseModel

from src.models.enums import WorkspaceStatus


class WorkspaceInfo(BaseModel):
    """What the frontend gets back — deliberately no host/port/
    credentials. The browser only ever needs a URL under this
    platform's own origin (`connect_url`); everything past that is
    proxy.py's problem, not the client's."""

    id: uuid.UUID
    chat_id: uuid.UUID
    status: WorkspaceStatus
    target_path: str
    connect_url: str
    terminal_enabled: bool

    model_config = {"from_attributes": False}
