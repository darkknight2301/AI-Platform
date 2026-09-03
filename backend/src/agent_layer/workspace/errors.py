"""Workspace-layer errors — same role agent_layer/errors.py plays."""
from __future__ import annotations


class WorkspaceError(Exception):
    default_safe_message = "The workspace is not currently available."

    def __init__(self, message: str | None = None, *, safe_message: str | None = None) -> None:
        super().__init__(message or self.default_safe_message)
        self.safe_message = safe_message or self.default_safe_message


class WorkspaceNotConfiguredError(WorkspaceError):
    """WORKSPACE_ENABLED is false, or required config is missing."""

    default_safe_message = "Workspaces are not enabled for this deployment."


class WorkspaceNotFoundError(WorkspaceError):
    default_safe_message = "This workspace does not exist."


class WorkspaceProvisioningError(WorkspaceError):
    """SSH connect / code-server startup failed."""

    default_safe_message = "Could not connect to the workspace. Please try again."


class WorkspaceForbiddenRouteError(WorkspaceError):
    """A proxied request targeted a route this platform refuses to
    forward — currently only the terminal WebSocket route. Distinct
    from WorkspaceProvisioningError: this is a deliberate policy
    refusal, not a failure."""

    default_safe_message = "This action is disabled for this workspace."
