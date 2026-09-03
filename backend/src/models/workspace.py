"""Workspace entity — the remote engineering workspace an agent-mode
chat's "Open VS Code" action connects to (ADR 0012, §Web IDE).

One row per chat that has ever requested a workspace (1:1 with
`Chat`, not with `AgentAdapter` runs — the same workspace persists
across a chat's whole lifetime). Deliberately holds no SSH
credentials itself: `ssh_key_path`/`ssh_username` reference a
backend-held key on disk (see `agent_layer/workspace/config.py`),
never a per-row secret in the database.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import WorkspaceStatus

if TYPE_CHECKING:
    from src.models.chat import Chat
    from src.models.user import User


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Remote workspace machine. No credentials here — see module
    # docstring; ssh_username pairs with one backend-held key
    # (WORKSPACE_SSH_KEY_PATH), not a per-workspace secret.
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_username: Mapped[str] = mapped_column(String(150), nullable=False)

    # The ONE folder this workspace's code-server is scoped to — the
    # actual access boundary (see ADR 0012's "Resolved: credentials
    # are shared/backend-held, not per-user"). Suggested/assigned by
    # the backend, not chosen by the browser.
    target_path: Mapped[str] = mapped_column(String(1000), nullable=False)

    # code-server's bound port on the remote host (localhost/private
    # interface only there — see ssh_manager.py). Assigned when the
    # workspace is first provisioned.
    code_server_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[WorkspaceStatus] = enum_column(
        WorkspaceStatus, name="workspace_status", nullable=False, default=WorkspaceStatus.PENDING
    )

    user: Mapped[User] = relationship()
    chat: Mapped[Chat] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Workspace id={self.id} chat_id={self.chat_id} status={self.status}>"
