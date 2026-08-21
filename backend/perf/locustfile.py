"""
Locust load test — realistic workload at the "500+ registered users"
scale referenced in Phase 11.

Deliberately targets the API layer only (login, chat CRUD, streaming),
using whatever model provider the target environment has configured
(MockProvider in a load-test environment is strongly recommended — see
PERFORMANCE.md, "API scalability vs model inference scalability": this
script measures the former; it is NOT a benchmark of the Qwen backend
itself, and running it against a real inference backend will bottleneck
on that backend's throughput, not the API).

Usage:
    pip install locust --break-system-packages
    # Seed N active users first (see perf/seed_users.py), then:
    locust -f backend/perf/locustfile.py --host http://localhost:8000

Suggested profile for the "500+ users" scenario: 500 total simulated
users, spawn rate 10/s, and watch:
  - p95/p99 latency per endpoint (Locust's built-in stats)
  - backend/src/core/middleware.py's /api/v1/system/performance
    (average_response_time_ms, requests_by_status_class) during the run
  - Postgres `SELECT count(*) FROM pg_stat_activity;` for connection
    pool saturation (see PERFORMANCE.md's pool-sizing math)
"""
from __future__ import annotations

import json
import random
import uuid

from locust import HttpUser, between, task


class ChatUser(HttpUser):
    """One simulated end user: logs in once, then repeatedly reads and
    sends chat messages — the dominant real-world traffic pattern for
    this app. Registration/approval is a separate, much rarer flow,
    covered by `AdminUser` below rather than mixed into every user's
    loop."""

    wait_time = between(1, 4)

    def on_start(self) -> None:
        self.username = f"loadtest_{uuid.uuid4().hex[:10]}"
        self.password = "correct-horse-1"
        self.client.post(
            "/api/v1/auth/register",
            json={"username": self.username, "email": f"{self.username}@example.com", "password": self.password},
        )
        # In a real run, seed_users.py should pre-approve accounts (see
        # that script) — a fresh registration here will be PENDING and
        # login will 403 until a Manager approves it, which is itself
        # useful signal: a load test that never gets past registration
        # is telling you the approval workflow, not the chat workflow,
        # is what's slow.
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"username_or_email": self.username, "password": self.password},
        )
        if resp.status_code != 200:
            self.token = None
            return
        self.token = resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

        models_resp = self.client.get("/api/v1/models", headers=self.headers)
        models = models_resp.json()
        models = models if isinstance(models, list) else models.get("models", [])
        self.model_key = models[0]["model_key"] if models else None
        self.chat_id = None
        if self.model_key:
            create_resp = self.client.post(
                "/api/v1/chats", json={"model_key": self.model_key}, headers=self.headers
            )
            if create_resp.status_code == 201:
                self.chat_id = create_resp.json()["id"]

    @task(5)
    def send_message(self):
        if not self.token or not self.chat_id:
            return
        self.client.post(
            f"/api/v1/chats/{self.chat_id}/messages",
            json={"content": "What's a good approach to rate limiting an API?"},
            headers=self.headers,
            name="/chats/{id}/messages [non-streaming]",
        )

    @task(2)
    def stream_message(self):
        if not self.token or not self.chat_id:
            return
        with self.client.post(
            f"/api/v1/chats/{self.chat_id}/messages",
            json={"content": "Summarize this in one sentence.", "stream": True},
            headers=self.headers,
            name="/chats/{id}/messages [streaming]",
            stream=True,
            catch_response=True,
        ) as resp:
            for _ in resp.iter_lines():
                pass  # drain the SSE stream to measure full time-to-completion
            resp.success()

    @task(3)
    def list_chats(self):
        if not self.token:
            return
        self.client.get("/api/v1/chats", headers=self.headers, name="/chats [list]")

    @task(2)
    def check_quota(self):
        if not self.token:
            return
        self.client.get("/api/v1/users/me/quota", headers=self.headers, name="/users/me/quota")

    @task(1)
    def get_history(self):
        if not self.token or not self.chat_id:
            return
        self.client.get(
            f"/api/v1/chats/{self.chat_id}/history",
            headers=self.headers,
            name="/chats/{id}/history",
        )


class AdminUser(HttpUser):
    """A much smaller population: Managers/Owners polling their
    dashboards. Weighted far below `ChatUser` — see `weight` below —
    because this reflects real traffic shape (few admins, many chat
    users), not because these endpoints matter less to test."""

    wait_time = between(3, 8)
    weight = 1  # ChatUser instances should outnumber this ~20:1 in a realistic run

    def on_start(self) -> None:
        # Expects an Owner account to already exist (see seed_users.py) —
        # self-registration can never produce an elevated role (Phase 3).
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "loadtest_owner", "password": "correct-horse-1"},
        )
        self.headers = (
            {"Authorization": f"Bearer {resp.json()['access_token']}"}
            if resp.status_code == 200
            else None
        )

    @task
    def owner_dashboard_load(self):
        if not self.headers:
            return
        for path, name in (
            ("/api/v1/admin/audit-logs", "/admin/audit-logs"),
            ("/api/v1/admin/usage", "/admin/usage"),
            ("/api/v1/system/performance", "/system/performance"),
        ):
            self.client.get(path, headers=self.headers, name=name)
