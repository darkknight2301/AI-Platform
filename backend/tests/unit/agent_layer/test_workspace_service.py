from __future__ import annotations

from src.agent_layer.workspace.workspace_service import is_forbidden_route


def test_terminal_routes_are_forbidden():
    assert is_forbidden_route("terminal/1")
    assert is_forbidden_route("some/pty/socket")


def test_ordinary_editor_routes_are_allowed():
    assert not is_forbidden_route("vscode-remote-resource")
    assert not is_forbidden_route("static/out/vs/workbench.js")
