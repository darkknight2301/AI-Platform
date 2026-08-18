# 0011 — Chat frontend: framework choice, streaming, and state design

## Status
Accepted — supersedes ADR 0004 ("minimal Vite/TypeScript frontend for the
foundation phase") now that real UI requirements exist.

## Context
ADR 0004 deliberately deferred a framework decision: "revisited once
actual UI requirements for the chat/business functionality are
known." Phase 8 is that point — a full chat interface with streaming,
markdown rendering, per-message revision history (undo/redo),
model selection, and live usage/quota display.

## Decisions

### 1. React + TypeScript + Vite, not vanilla TypeScript
The vanilla-TS foundation page had no interactive state to manage.
This phase requires many pieces of interdependent, frequently-updating
UI state (active chat, streaming buffer, revision navigation, quota
countdown) — exactly what a component framework with a rendering
model exists for. React was chosen over other frameworks primarily
because it's the most broadly-known choice for this kind of app,
keeping the codebase approachable; no framework-specific backend
coupling exists either way, since the frontend only ever talks to the
versioned JSON/SSE HTTP API.

### 2. No UI copied from ChatGPT/Claude — a distinct visual identity
Layout *structure* (sidebar + chat pane, matching the phase's own
required wireframe) is common to virtually every chat product and
isn't proprietary. Visual identity — color palette (charcoal sidebar +
indigo accent + warm-paper content pane, `src/styles.css`), typography
(system sans for UI text, monospace reserved for technical readouts:
model badges, token counts, the usage bar), and component styling are
original, not sampled from any specific product.

### 3. The frontend contains zero model-specific or streaming-format-specific logic
`src/api/stream.ts` is the ONLY file that parses the SSE wire format,
and it parses exactly one shape: `StreamEventOut`
(`delta`, `is_final`, `finish_reason`, `message_id`, token counts) —
the same "common streaming format regardless of model implementation"
established server-side in Phase 6 (ADR 0009) for exactly this reason.
Nothing in the frontend knows whether a chat is backed by
`MockProvider` or `QwenProvider`; it only ever sees a `model_key`
string returned by `GET /api/v1/models` and passes it back verbatim.

### 4. `EventSource` was rejected in favor of `fetch` + `ReadableStream`
The browser's native `EventSource` API only supports GET requests and
cannot set custom headers, so it cannot carry the `Authorization:
Bearer` JWT the backend requires (Phase 3) or send the JSON request
body the streaming endpoints expect (`{"content": ..., "stream":
true}`). `src/api/stream.ts` instead uses `fetch` with a manually-read
`ReadableStream`, decoding and splitting on the same `\n\n`-delimited
`data: {...}` framing the backend emits — no third-party SSE client
library needed for this.

### 5. New backend endpoint: `GET /api/v1/models`
No endpoint existed for an ordinary `Role.USER` to discover which
models they may create a chat against — `GET /api/v1/system/models`
is Developer+, `GET /api/v1/admin/models` is Owner-only (both Phase
3). Added `src/api/v1/routers/models.py`: any authenticated user,
enabled models only, minimal fields (no `config_metadata`, which may
contain operational detail not meant for end users). This is a small,
clearly-scoped backend addition made *because* Phase 8 exposed a real
gap in the existing API surface, not a reopening of earlier phases'
scope.

### 6. State design: refetch-after-mutation, not fine-grained optimistic patching
After any mutating action (send, edit, regenerate, activate, rename,
archive, delete) completes, the frontend refetches the chat list
and/or message history from the backend rather than hand-patching
local state to match every possible server-side side effect (sequence
numbers, revision counts, chat `revision` bumps, quota changes). Given
the revision/branching model's complexity (ADR 0009), correctness here
matters more than shaving a request; the one exception is the
in-flight streaming buffer itself, which is necessarily local state
updated incrementally as `StreamEventOut` chunks arrive, replaced by
the authoritative persisted message once the stream ends and history
is refetched.

### 7. Undo/redo maps directly onto revision activation, per message
Each message with `revision_count > 1` shows a `‹ n/total ›` control
(`src/components/RevisionNav.tsx`). Stepping it calls
`POST /messages/{id}/activate` on the neighboring revision — the same
server-persisted primitive Phase 6/7 already expose. There is no
separate client-side undo stack; "undo" and "redo" are just navigating
a message's own revision history in either direction, which is also
why undo/redo state survives a page reload (it's derived entirely from
the backend, not `sessionStorage`/browser state).

### 8. No attachments, file upload, image upload, or paperclip button
Per this phase's explicit exclusions. There is no code path, hidden or
otherwise, for multipart uploads anywhere in the frontend.

## Consequences
- Bundle includes `react-markdown` + `remark-gfm` (markdown/GFM
  rendering, including fenced code blocks) and `lucide-react` (icons)
  as the only notable runtime dependencies beyond React itself and
  `react-router-dom` for the three-route app (`/login`, `/register`,
  `/`).
- No syntax highlighting library is included — code blocks render in
  a monospace block with a copy button, satisfying "code blocks" and
  "copy" without adding a highlighting dependency; this can be added
  later without changing the message-rendering architecture.
- The dev server proxies `/api` to `localhost:8000` (`vite.config.ts`)
  so `npm run dev` works against a locally-running backend with no
  CORS configuration needed in development; production deployment
  serves the built frontend through Nginx, which already proxies
  `/api/*` to the backend (Phase 1's `nginx/nginx.conf.template`).
