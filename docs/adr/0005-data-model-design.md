# 0005 — Data model design: UUID keys, portable enums, denormalized usage accounting

## Status
Accepted

## Context
Phase 2 needed a relational schema for users, groups, roles, chats,
messages, models, usage, and audit logs, sized for 500+ concurrent
users, with database-enforced integrity (foreign keys, indexes,
unique/check constraints) rather than integrity enforced only in
application code.

Several cross-cutting design choices affect every table, so they're
recorded together here rather than repeated per-entity.

## Decisions

### 1. UUID surrogate primary keys everywhere
All tables use a `uuid.uuid4()`-generated UUID primary key
(`sqlalchemy.Uuid`) rather than an auto-incrementing integer.
Rationale: IDs are safe to expose in API responses/URLs without
leaking sequential volume (e.g. total user count), and can be
generated before an insert if a future feature needs client-side ID
assignment. Trade-off: UUIDs are larger than integers (16 bytes vs.
4/8), which matters more for very high-volume tables — acceptable at
the 500+ user scale this system targets; can be revisited if a
specific table's write volume becomes a bottleneck.

### 2. Enum columns stored as VARCHAR + CHECK constraint, not native PostgreSQL ENUM
Using `sqlalchemy.Enum(..., native_enum=False, create_constraint=True)`
instead of native PostgreSQL enum types. Rationale:
- Identical schema works against SQLite (used for fast unit/local
  tests) and PostgreSQL (production) — no per-backend branching.
- Adding a new enum value later is an ordinary Alembic migration
  instead of PostgreSQL's `ALTER TYPE ... ADD VALUE`, which cannot run
  inside the same transaction as other DDL/DML in older PostgreSQL
  versions and complicates rollout.
- Invalid values are still rejected at the database layer via the
  generated `CHECK` constraint — this is not a relaxation of data
  integrity, only a different mechanism for enforcing it.

### 3. `Role` as a flat, ordered enum rather than a permissions table
`Role` (`USER`, `MANAGER`, `DEVELOPER`, `OWNER`) is one column on
`users`, with an accompanying `ROLE_RANK` mapping giving each value a
numeric rank. This satisfies the "prefer role definitions that do not
require hardcoding authorization logic throughout the application"
guidance: a future authorization layer can implement one central
"does this role meet this minimum rank" check, rather than every
endpoint hardcoding `if role == "OWNER" or role == "DEVELOPER"`-style
conditions. A full permissions/ACL table was considered and rejected
as premature — no endpoints exist yet to authorize, and the four named
roles map cleanly onto a simple hierarchy for now. This can be
revisited if a future phase needs per-permission (not just per-role)
granularity.

### 4. `usage_records` is denormalized against `chat_id`/`user_id`
Even though a `Usage` row is reachable via `message_id` ->
`messages.chat_id` -> `chats.user_id`, `usage_records` also stores
`user_id` and `chat_id` directly. Rationale: usage/quota reporting
("how many tokens has this user used this month") is an expected
frequent query pattern at 500+ users, and requiring a join through
`messages` and `chats` for every such query is unnecessary overhead
for data that is fundamentally accounting data, not conversational
data. The trade-off (denormalization can drift if not written
carefully) is mitigated by writing `usage_records` from a single
service-layer code path in a later phase, not from multiple places.

### 5. Token-sum integrity via CHECK constraints
Both `messages` and `usage_records` enforce
`total_tokens = input_tokens + output_tokens` and non-negative token
counts via `CHECK` constraints, not just application-level validation.
This guarantees the invariant holds even for direct database access,
bulk loads, or future code paths that might otherwise bypass
application validation.

### 6. Cascade/restrict/set-null choices per relationship
- `User -> Chat -> Message`: `ON DELETE CASCADE` — deleting a user's
  account should not leave orphaned chats/messages.
- `Group -> User`: `ON DELETE SET NULL` — deleting a group must not
  delete its members; they simply become groupless.
- `AIModel -> Chat`/`Usage`: `ON DELETE RESTRICT` — a model backend
  that has been used must not be deletable out from under existing
  chats/usage history; disable it (`is_enabled = false`) instead.
- `Usage -> Chat`/`Message`: `ON DELETE SET NULL` — usage/accounting
  records are financial/reporting data and must outlive the
  conversational data they originated from.
- `AuditLog -> User` (actor): `ON DELETE SET NULL`, and
  `target_type`/`target_id` are plain strings, not foreign keys —
  audit history must remain even after the actor or target no longer
  exists.

## Consequences
- The schema can be created from scratch via `alembic upgrade head`
  against a fresh PostgreSQL database (verified) and torn down via
  `alembic downgrade base` (verified round-trip).
- Invalid data (bad enum values, negative/mismatched token counts,
  duplicate usernames/emails) is rejected at the database layer, not
  only in application code — verified via integration tests against a
  real PostgreSQL instance in `tests/integration/test_data_model.py`.
- No authentication/authorization *logic* is implied by this ADR — only
  the data shape it will sit on top of in a later phase.
