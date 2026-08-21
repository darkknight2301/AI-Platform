# API Guide

Documents the API as it actually exists in `backend/src/api/v1/routers/`
as of Phase 13. Nothing here describes planned/hypothetical endpoints —
if it's not listed, it isn't implemented. All paths are relative to
`API_V1_PREFIX` (default `/api/v1`). Interactive OpenAPI docs are also
available at `/docs` (Swagger UI) and `/redoc` whenever the API is
running — this document is the narrative companion, not a replacement.

Auth: every endpoint except `POST /auth/register`, `POST /auth/login`,
and `GET /health` requires `Authorization: Bearer <access_token>`.

## Auth (`/auth`)

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/auth/register` | none | Creates a `PENDING` user. Never accepts a role — self-registration can only ever produce `Role.USER`, and only after Manager approval (see ADR 0006). |
| POST | `/auth/login` | none | Returns a bearer access token. Rejects `PENDING`/`SUSPENDED`/`REJECTED` accounts with a specific status, not a generic 401. Locks out an identifier for 15 min after 5 recent failures (Phase 10). |
| POST | `/auth/logout` | any authenticated | Revokes the current session (its JWT `jti` is marked revoked server-side — logout is real, not just "forget the token client-side"). |
| GET | `/auth/me` | any authenticated | Current user's public profile. |

## Users (`/users`)

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/users/me` | any | Own profile. |
| GET | `/users/me/usage` | any | Own usage records. |
| GET | `/users/me/quota` | any | Own token quota + chat limit status. |
| GET | `/users` | Manager+ | `?status=PENDING` etc. Manager sees only their own group; Owner sees all (see `services/user_service.py`). |
| GET | `/users/me/activity` | Manager+ | Audit entries **for actions the caller themselves performed** — Manager dashboard's "Authorized activity" (Phase 9/10). |
| GET | `/users/groups/{group_id}` | Manager+ | Own group only for a Manager; any group for an Owner. |
| GET | `/users/groups/{group_id}/usage` | Manager+ | Same scoping. |
| GET | `/users/{user_id}` | Manager+ | Scoped to caller's manageable group(s). |
| POST | `/users/{user_id}/approve` | Manager+ | |
| POST | `/users/{user_id}/reject` | Manager+ | |
| GET | `/users/{user_id}/quota` | Manager+ | |

## Chats (`/chats`)

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/chats` | any | Creates a chat bound to a `model_key`. Enforced against the caller's active-chat limit. |
| GET | `/chats` | any | Caller's own chats only (ownership-scoped at the repository layer — see ADR 0009). |
| GET | `/chats/{chat_id}` | owner only | |
| PATCH | `/chats/{chat_id}` | owner only | Rename. |
| DELETE | `/chats/{chat_id}` | owner only | Soft delete (`status=DELETED`) — never a hard delete; audited as `DELETE_CHAT`. |
| GET | `/chats/{chat_id}/history` | owner only | Full message tree with all revisions. |
| POST | `/chats/{chat_id}/messages` | owner only | Send a prompt. `stream=true` in the body switches to an SSE response; enforces the token quota reservation described in ADR 0010 either way. |

## Messages (`/messages`)

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/messages/{message_id}/edit` | owner only | Creates a new prompt revision at that slot (audited as `PROMPT_EDIT`) and regenerates the paired assistant reply. |
| POST | `/messages/{message_id}/regenerate` | owner only | New assistant-message revision; prompt untouched. |
| GET | `/messages/{message_id}/revisions` | owner only | All revisions at a message's slot — backs undo/redo. |
| POST | `/messages/{message_id}/activate` | owner only | Switches which revision is "active" (undo/redo without generating a new one). |

## Models (`/models`)

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/models` | any authenticated | Enabled models available to select from, with capability info. |

## System (`/system`) — Developer dashboard

Every route requires Developer role or above.

| Method | Path | Notes |
|---|---|---|
| GET | `/system/logs` | Recent structured log entries. Operational metadata only — never prompts/replies (Phase 10). |
| GET | `/system/models` | Live model status (enabled/disabled, provider, category). |
| GET | `/system/diagnostics` | DB reachability, uptime, server time. |
| GET | `/system/performance` | Request counts by status class, average response time. |

## Admin (`/admin`) — Owner dashboard

Every route requires Owner role.

| Method | Path | Notes |
|---|---|---|
| GET / POST | `/admin/groups` | |
| PATCH | `/admin/groups/{group_id}` | Includes quota-override fields — Owner-only, not exposed via the Manager-facing `GroupSummary`. |
| PATCH | `/admin/users/{user_id}` | Role/status/group reassignment, quota overrides. |
| GET / POST | `/admin/models` | Model management — register/enable/disable. |
| PATCH | `/admin/models/{model_id}` | |
| GET | `/admin/audit-logs` | Global audit trail. |
| GET | `/admin/usage` | Global usage report. |
| GET | `/admin/config` | Non-secret configuration snapshot — never includes `secret_key`/`database_url` (verified in `test_phase10_security.py`). |

## Health (`/health`)

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/health` | none | Liveness only — process is up. Does not check the database; use `/system/diagnostics` (Developer+) for that. |

## Streaming (SSE) response shape

`POST /chats/{chat_id}/messages` with `stream=true` returns
`text/event-stream`. Each event's `data` is a JSON-encoded
`StreamingChunk`-derived payload (`delta`, `is_final`,
`finish_reason`, `usage` on the final chunk) — see
`frontend/src/api/stream.ts` for the consuming implementation and
`backend/src/model_layer/schemas.py::StreamingChunk` for the exact
shape.

## Error shape

All error responses are `{"detail": "..."}` (FastAPI's default
`HTTPException` handling — Phase 10 adds structured server-side
logging of the exception type, but never changes the response body
shape). Status codes follow normal HTTP semantics: 401
(unauthenticated), 403 (authenticated but not authorized — RBAC/group
isolation/ownership failures), 404 (genuinely absent — a resource ID
that was never valid), 409 (conflict, e.g. duplicate username, or an
invalid revision-state operation), 429 (rate limited, login lockout,
chat-limit exceeded, or token-quota exceeded — see
`backend/src/api/error_mapping.py`), 502 (the model backend itself
failed — distinct from a 500, since the API process itself is
healthy), 500 (unhandled).

**Known trade-off, not a bug**: ownership failures return 403 (chat
exists, isn't yours) while a genuinely unknown ID returns 404 — see
`services/conversation_service.py::_get_owned_chat`. This lets an
authenticated caller distinguish "exists" from "doesn't exist" for a
chat ID that isn't theirs, which is a minor enumeration signal. Listed
as a known limitation in the Phase 13 architecture review rather than
changed here, since collapsing both to 404 has its own downside
(harder to debug legitimate client errors) and no exploit path beyond
existence-confirmation was identified.
