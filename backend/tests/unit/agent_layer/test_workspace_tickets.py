from __future__ import annotations

import uuid

from src.agent_layer.workspace import tickets


def test_ticket_round_trips_for_matching_workspace():
    user_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    ticket = tickets.issue_ticket(user_id=user_id, workspace_id=workspace_id, ttl_seconds=60)
    assert tickets.verify_ticket(ticket, workspace_id=workspace_id) == user_id


def test_ticket_rejected_for_different_workspace():
    user_id = uuid.uuid4()
    ticket = tickets.issue_ticket(user_id=user_id, workspace_id=uuid.uuid4(), ttl_seconds=60)
    assert tickets.verify_ticket(ticket, workspace_id=uuid.uuid4()) is None


def test_expired_ticket_rejected():
    user_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    ticket = tickets.issue_ticket(user_id=user_id, workspace_id=workspace_id, ttl_seconds=-1)
    assert tickets.verify_ticket(ticket, workspace_id=workspace_id) is None


def test_garbage_ticket_rejected():
    assert tickets.verify_ticket("not-a-jwt", workspace_id=uuid.uuid4()) is None
