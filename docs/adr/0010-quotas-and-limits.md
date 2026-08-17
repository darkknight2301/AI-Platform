# 0010 — Token quotas and chat limits: resolution, renewal, concurrency

## Status
Accepted

## Context
Phase 7 requires configurable chat-count and token-usage limits with a
global default / group override / user override hierarchy, a defined
renewal policy, concurrency safety ("multiple simultaneous requests
cannot bypass quota"), backend-authoritative accounting, a documented
charging policy for failed requests, and enough information in the API
for a frontend to render "62%", "62,000 / 100,000", and a renewal
time.

## Decisions

### 1. Resolution order: user override > group override > global default
`User.max_active_chats_override` / `User.token_quota_override` and
`Group.max_active_chats_override` / `Group.token_quota_override`
(nullable `Integer` columns, Phase 7 migration) are checked in that
order; the first non-NULL value wins, else
`Settings.default_max_active_chats` / `default_token_quota` (env-
configurable) applies. See `src/services/quota_service.py`'s
`get_effective_max_active_chats`/`get_effective_token_quota`. This
means: each user's effective limit is a single resolved number, not a
quota shared/pooled across a group's members — group membership only
determines which fallback value applies. Overrides are managed via the
existing Owner admin API (`PATCH /admin/groups/{id}`,
`PATCH /admin/users/{id}` — both extended in this phase), using the
same `exclude_unset` convention as `ModelUpdate` (Phase 3): an omitted
field is unchanged, an explicit `null` clears the override.

### 2. Renewal policy: configurable, always derived from persisted data
`Settings.token_quota_renewal_policy` (env var
`TOKEN_QUOTA_RENEWAL_POLICY`) is one of:
  - `ROLLING_24H` (default): usage counted is always the trailing 24
    hours from "now" — continuously sliding, no fixed reset instant.
  - `DAILY_RESET_UTC`: usage counted is since the most recent UTC
    midnight — fixed, predictable, shared reset instant for everyone.

Both are computed as `SUM(usage_records.total_tokens)` over the
relevant window (`quota_repository.sum_usage_tokens_since`) — never a
separately-mutable counter that could drift from the authoritative
ledger or be bypassed by retrying a request. This is a single
system-wide setting, not per-group/user overridable (unlike the limit
*values* — see decision 1); a renewal policy is a facet of the
accounting method, not per-tenant configuration in the same sense.

For the UI's "renewal time": `DAILY_RESET_UTC` reports the next UTC
midnight, exactly. `ROLLING_24H` has no single instant at which *all*
capacity returns — it reports the next moment *any* capacity frees up
(the oldest in-window usage row's timestamp + 24h), which is the most
useful single number to show for a continuously-sliding window.

### 3. Concurrency safety: `pg_advisory_xact_lock` + a short-lived reservation table

**Chat limit.** `enforce_chat_limit` acquires a transaction-scoped
advisory lock keyed on the user's id
(`quota_repository.advisory_lock_key`, `pg_advisory_xact_lock`),
counts active chats, and only then permits the caller to insert the
new chat in the same transaction. Because there's no external (model
provider) call involved, holding the lock for the whole
check-then-insert is cheap and correct: two simultaneous
chat-creation requests serialize on the lock, and the second one's
count always reflects the first's just-created chat.

**Token quota.** Holding a lock (and a DB connection) across an entire
model generation — which can take many seconds, especially streamed —
would be expensive and would serialize a user's requests far more than
necessary. Instead, `reserve_tokens` holds the lock only for the brief
check-and-insert step: it sums actual usage (`usage_records`) *plus*
any other currently-open `quota_reservations` rows for that user, and
if a conservative estimate (`Settings.quota_reservation_estimated_output_tokens`,
default 2048 — deliberately not tied to any specific model's real
output-token accounting, which is never known until generation
completes) would push the total over quota, rejects immediately.
Otherwise it inserts a `QuotaReservation` row and commits (releasing
the lock) *before* the model is ever called. Any other truly-concurrent
request for the same user, arriving while generation is still in
flight, will see that reservation in its own sum and correctly be
rejected if it would exceed quota — this is what closes the race a
bare "check current usage" would leave open.

`release_reservation` deletes the row after the generation attempt
finishes, success or failure, and **commits immediately** — not
folded into the caller's later commit — specifically so that if the
caller's overall operation later raises and its own transaction rolls
back, the reservation release itself isn't undone (which would
otherwise permanently leak an orphaned reservation row).

### 4. Documented failed-request charging policy: failures are never charged
A model call that raises (`ChatServiceError`, from Phase 5/6's
provider-agnostic error handling) always results in
`release_reservation` being called and **no** `Usage` row being
inserted — the reservation is released, nothing is charged. This
applies uniformly to `send_message`, `regenerate_message`, the
cascading regeneration inside `edit_message`, and all three streaming
variants (`stream_generation`'s `finish_reason == "error"` branch and
its defensive `except ChatServiceError` branch both release the
reservation before yielding the terminal event). This mirrors, and is
motivated by, Phase 6's existing policy (ADR 0009) that a failed
generation never persists a message — no message persisted, no tokens
charged is the natural extension of that same principle to quota
accounting.

A rejection *before* generation is attempted (chat limit or token
quota already exceeded) also persists nothing new — for streaming,
this means the already-flushed prompt from `prepare_*_stream` is
rolled back along with the raised `TokenQuotaExceededError`, since
that exception isn't caught by the "keep the prompt on
`ChatServiceError`" logic (a quota rejection is a full rejection of
the operation, not a mid-flight generation failure), consistent
between streaming and non-streaming paths.

### 5. `Usage` (billing ledger) vs `QuotaReservation` (concurrency scaffolding) vs `Group`/`User` overrides (limit configuration)
Three distinct, single-purpose pieces of state, deliberately not
merged into one:
  - `usage_records` (Phase 2/3): the durable, authoritative accounting
    ledger. Never mutated after insert; always what "used tokens" for
    reporting/billing ultimately means.
  - `quota_reservations` (Phase 7): short-lived rows that exist only
    for the duration of one in-flight generation, purely to make
    concurrent quota checks safe. Never read for historical/reporting
    purposes — only summed into the *live* check.
  - `Group`/`User` override columns (Phase 7): admin-configured limit
    *values*, not usage.

## Consequences
- Chat-limit and token-quota concurrency safety both rely on
  PostgreSQL's `pg_advisory_xact_lock` — SQLite (used for the fast
  unit-test suite elsewhere in this codebase) cannot run these tests;
  `tests/integration/test_quota.py` follows the established
  Postgres-integration-test pattern (Phase 2/3/6) instead.
- `GET /api/v1/users/me/quota` (any authenticated user) and
  `GET /api/v1/users/{id}/quota` (self, Owner, or Manager-of-same-group
  — reusing Phase 3's `user_service.get_user_for_requester`
  authorization) expose `used_tokens`, `quota_tokens`, `percent_used`,
  `renewal_policy`, `renews_at`, `active_chats`, `max_active_chats` —
  everything the acceptance criteria's UI example ("62%",
  "62,000 / 100,000", "Renewal time") needs.
- `DELETE /chats/{id}` (Phase 6) is unaffected by the chat limit — it
  still only soft-deletes on explicit request. The limit itself never
  triggers any deletion; a user at their limit must free a slot
  (archive/delete a chat) or ask an Owner to raise it.
- The reservation estimate (`quota_reservation_estimated_output_tokens`)
  is a deliberately simple, single global constant rather than a
  per-model or per-request-derived figure. A future phase could make
  it capability-aware (e.g. derived from a model's configured
  `max_output_tokens`) for tighter reservations; today it trades some
  reservation precision for simplicity.
