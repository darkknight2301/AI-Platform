# 0009 — Chat backend: revision model, ownership, streaming persistence

## Status
Accepted

## Context
Phase 6 implements the complete chat backend: chat CRUD, sending
prompts, streaming, prompt editing without destroying history,
regenerating replies, and server-persisted undo/redo — all with
per-operation authorization. Several cross-cutting design decisions
apply to the whole feature, recorded together here.

## Decisions

### 1. Revisions are rows, not overwrites — the "slot" model
A logical position in a conversation (one user prompt, or the one
assistant reply that follows it) is a "slot". Editing or regenerating
never mutates or deletes a row; it inserts a new row in the same slot
and flips `is_active` so exactly one row per slot is current. Full
detail (including why `root_message_id` is a direct pointer to the
slot's root rather than a linked list of predecessors, and why
`sequence_number` is separate from `created_at`) is in the module
docstring of `src/models/message.py`. This is what makes "do not
overwrite history; maintain revisions" concretely true: `git blame`
-style, every v1/v2/v3 is a real, independently queryable row
(`GET /messages/{id}/revisions`), forever.

### 2. Undo/redo is "activate a revision", not a separate history stack
`POST /messages/{id}/activate` makes any revision in a slot the active
one, deactivating its siblings. This is deliberately symmetric
(works identically for a user prompt or an assistant reply) and
entirely server-persisted — nothing about which revision is "current"
lives only in browser state. Scope limitation: activating a user
message revision does not automatically regenerate a matching paired
reply (the reply that was originally generated for that exact prompt
text isn't tracked as a pairing beyond "whatever's active in the next
slot"). This was a deliberate simplification given phase scope; a
future phase could track prompt/reply pairing per revision if that
level of undo fidelity is needed.

### 3. Editing a prompt cascades exactly one turn forward, no further
`POST /messages/{id}/edit` creates a new revision of the prompt and,
if a reply already exists immediately after it in the active thread,
regenerates that one reply for the edited prompt. It does not touch
anything beyond that turn. Cascading edits through an entire
downstream conversation was considered and rejected as out of scope —
most real conversations don't continue significantly past a point the
user then decides to edit, and the simpler model is far easier to
reason about and test.

### 4. Ownership is strict — no Owner/Manager override
Every chat/message operation is gated through
`ConversationService._get_owned_chat`/`_get_owned_message`, which
require `chat.user_id == requester.id` exactly. Unlike Phase 3's admin
surface (which explicitly grants Owner broad management rights over
users/groups/models), there is deliberately no bypass here — chats are
private content, consistent with Phase 3's stance that
`Role.DEVELOPER` must not get "unrestricted private chat access."
`ChatAccessDeniedError` (403) and `ChatNotFoundError` (404) are
distinct exception types even though both often just look like "you
can't see this" to the end user, so ownership-denial and
genuinely-missing-data remain distinguishable in tests and logs.

### 5. Failure ordering: a model call failing never destroys state
Every mutation that depends on a model call succeeding — deactivating
an old revision, inserting a new one — happens strictly after that
call returns. `ConversationService._call_model` (which can raise
`ChatServiceError`) is always a separate step from
`_persist_assistant_message` (a pure insert). Concretely: a failed
`send_message` still keeps the user's prompt (committed immediately,
before the model call); a failed `regenerate_message` leaves the
previous reply active and untouched, not silently deactivated with
nothing in its place.

### 6. Streaming persistence uses a fresh session, not the request-scoped one
`stream_generation` (a module-level function, not a `ConversationService`
method) persists the completed message using a session obtained from
an explicit `session_factory` parameter — never the request-scoped
session injected via `Depends(get_db)`. A `StreamingResponse`'s body
generator is consumed by the ASGI server after the route handler
function returns; relying on a request-scoped dependency's session
staying open for that entire duration is fragile across FastAPI/
Starlette versions. Using a distinct, explicitly-passed session avoids
the question entirely. `src.api.deps.get_session_factory` is a small,
overridable dependency (mirroring `get_db`) so tests can point it at
the same test database `get_db` is overridden to use — see
`tests/integration/test_chat_backend.py::test_send_message_streaming`.

### 7. The streaming wire format is `StreamEventOut`, uniform for every provider
Every `data:` line on a streaming endpoint is a `StreamEventOut` — the
non-final chunks carry only `delta`; the terminal chunk carries
`is_final=true`, `finish_reason`, the persisted `message_id`, and
token counts. This is the same shape regardless of whether the
provider behind it is `MockProvider` or `QwenProvider` (Phase 5's
`StreamingChunk` already made this true at the model layer; Phase 6
carries that guarantee through to the HTTP wire format, fulfilling
Phase 5 ADR 0008's forward-looking "the frontend must eventually
receive a common streaming format regardless of model implementation").
A stream that fails — before or after producing content — always ends
with exactly one terminal event (`finish_reason="error"`), never a raw
exception or a dropped connection with no signal; see
`src/model_layer/errors.py`'s streaming-interruption contract, which
`stream_generation` extends one layer further out.

### 8. Content is passed through verbatim — markdown/code blocks are a frontend concern
Message content is stored and returned as opaque UTF-8 text (`Text`
column, `str` in every schema) with no server-side transformation.
"Markdown response" / "code blocks" as backend requirements are
satisfied by *not* mangling the text a model produces — rendering
markdown/fenced code blocks is a rendering concern for whichever
frontend eventually consumes this API, not this phase's chat backend
(no chat UI exists yet in `frontend/`, only a foundation health-check
page — see Phase 1/README status). Verified in
`test_send_message_and_history`, which round-trips a fenced code block
and asserts byte-for-byte equality.

### 9. `Usage` is written per generation, `AuditLog` is not
Every successful assistant reply writes a `Usage` row (already
established in Phase 2/3 for token accounting). Chat/message CRUD does
NOT write `AuditLog` entries — that table remains reserved for
account/security/administrative actions (register, login, approvals,
admin changes), not high-volume conversational content, to avoid
diluting the security audit trail with routine chat activity.

## Consequences
- The full flow (create chat -> send -> edit -> regenerate -> history)
  is verified end-to-end against the real `QwenProvider` (via
  `httpx.MockTransport`, no live inference server) in
  `tests/integration/test_chat_backend.py::test_full_chat_flow_against_qwen_provider`
  — the concrete proof of "complete backend chat flow works against
  the Qwen model providers."
- No chat data is ever hard-deleted: `DELETE /chats/{id}` is a soft
  delete (`status=DELETED`); message revisions are never removed.
- Building model context from the active thread with no length cap
  (`list_active_thread(..., limit=1000)`) is a known simplification —
  a future phase should truncate/summarize context against each
  model's `max_context_tokens` (already exposed via
  `ModelCapabilities`) rather than always sending the full history.
