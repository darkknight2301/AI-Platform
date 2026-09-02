# 0012 — ILA agent integration and browser Web IDE

## Status
**Proposed — not implemented.** Per explicit instruction, no code
changes have been made yet. This is the design to review/approve
before Phase 1 coding starts. Two open blockers before implementation
can begin are called out at the end.

## Context

ILA is a Python agent module (not a model) that uses models, tools,
and knowledge to produce engineering output, optionally backed by a
remote development workspace. It needs to sit *above* the existing
model layer, be fully reversible (env-flag off restores today's
behavior with no code changes), and eventually be one of several
agents/tools the platform supports — so the integration point matters
more than the ILA-specific code.

Two things were inspected before proposing anything below:

1. **The existing model abstraction** (`src/model_layer/`, ADR 0007):
   `ChatService → ModelRouter → ModelRegistry → ModelProvider`. Clean,
   but built for one thing — a chat turn resolves to exactly one
   provider that returns/streams text. An agent that plans, calls
   tools, and may run for much longer than one HTTP request doesn't
   fit that shape, and forcing it to (e.g. implementing `generate()`
   that secretly does agent work) would hide what's actually happening
   behind an interface that promises something simpler than it is —
   this is why the instruction to *not* force ILA into `ModelProvider`
   is correct, not just a preference.

2. **A real, load-bearing constraint the design must satisfy**:
   `Chat.model_id` and `Usage.model_id` are both **non-nullable**
   foreign keys to the `models` table (`src/models/chat.py`,
   `src/models/usage.py`). Every existing chat and every existing
   usage record is required to point at a real `AIModel` row. This is
   the one place where "technically required" reuse of existing
   infrastructure actually applies — not to `ModelProvider` (which
   ILA should not implement), but to the `models`/`AIModel` table,
   which is accounting/identity data, not a provider registration.

## Decision

### High-level shape

```text
                     Chat Service (existing, unchanged)
                             |
                new: ChatService checks Chat.agent_key
              (added at the ONE existing branch point where
               chat_service currently calls the router — see
               "Files/classes to modify")
                    /                              \
                   /                                \
        agent_key IS NULL                    agent_key IS SET
        (today's behavior,                   (new)
         100% unchanged)                            |
                   |                                 v
                   v                        Agent Router (new, tiny)
         ModelRouter -> ModelRegistry           |
         -> QwenCoderProvider /                 v
            QwenNLPProvider                AgentRegistry (new, mirrors
         (existing, byte-for-byte           ModelRegistry's shape —
          unchanged)                        agent_key -> AgentAdapter)
                                                    |
                                                    v
                                          ILAAgentAdapter (new, thin)
                                                    |
                                                    v
                                     ILA module (yours — imported,
                                     not reimplemented) which itself
                                     may call ModelRouter for its own
                                     model needs (reuse, see below)
                                                    |
                                                    v
                                        Optional: Workspace/Web IDE
                                        (separate subsystem, §Web IDE)
```

The two paths never share a code path after the branch. Nothing about
`ModelRouter`, `ModelRegistry`, `QwenCoderProvider`, `QwenNLPProvider`,
or the Qwen-only request/response shape changes.

### New package: `src/agent_layer/`

Deliberately a sibling of `src/model_layer/`, not inside it — same
reasoning as ADR 0008's "Qwen-specific concerns stay inside
`providers/qwen/`": agent-specific concerns stay out of everything
that doesn't need to know about agents.

```text
src/agent_layer/
  __init__.py
  agent_interface.py    AgentAdapter ABC — deliberately NOT
                         ModelProvider. Minimal, agent-shaped contract:
                         run(request) -> AgentResult, and a streaming
                         variant, plus a way to report what "step" or
                         "tool" is currently executing (agents are not
                         single-shot text generation — the interface
                         should not pretend otherwise)
  schemas.py             AgentRequest/AgentResult/AgentEvent —
                         analogous to model_layer/schemas.py but
                         shaped for multi-step agent output (a
                         sequence of events: tool calls, intermediate
                         reasoning if surfaced, final output,
                         optional workspace reference), not a single
                         text blob
  registry.py             AgentRegistry — agent_key -> AgentAdapter,
                          intentionally structurally similar to
                          ModelRegistry (same register/get/list shape)
                          so a future second agent is "implement
                          AgentAdapter + register it", identical
                          pattern to adding a model provider today
  bootstrap.py             reads ILA_ENABLED, constructs and
                          registers ILAAgentAdapter — mirrors
                          model_layer/bootstrap.py exactly
  adapters/
    ila_adapter.py          ILAAgentAdapter(AgentAdapter) — thin
                            wrapper around the actual ILA module
                            (import, not reimplementation). This file
                            cannot be finalized until ILA's real
                            interface is inspected — see blockers.
  workspace/                 (see Web IDE section below — separate
                              concern, only coupled to agent_layer via
                              AgentResult optionally carrying a
                              workspace_id)
```

### Reuse, concretely

- **Models**: if ILA needs an LLM call internally, `ILAAgentAdapter`
  is constructed with a reference to the existing `ModelRouter` (the
  same instance `ChatService` already holds) and can call
  `router.route(model_key)` / `router.route_by_category(category)`
  itself — ILA gets Qwen access through the exact same seam
  everything else does, no second HTTP client, no duplicated
  provider logic. This is the concrete answer to "reuse existing
  model/provider infrastructure where appropriate" without ILA
  becoming a `ModelProvider`.
- **Quotas**: `QuotaService`'s advisory-lock reservation pattern
  (ADR 0010) is reused as-is for tokens ILA's internal model calls
  consume — `ILAAgentAdapter` reports usage back through the same
  `Usage`-row-writing path `ChatService` already uses, keyed off
  ILA's own placeholder `AIModel` row (below) or the specific Qwen
  model it actually called, whichever gives more useful reporting;
  a concrete choice here should be made once ILA's actual model-usage
  pattern is known (see blockers) — flagged, not decided prematurely.
- **Auth/RBAC/ownership**: unchanged. A chat is still owned by exactly
  one user, still goes through the same `require_min_role`/ownership
  checks in `conversation_service.py` regardless of whether it's a
  Qwen chat or an ILA chat — the branch happens *after* those checks,
  not instead of them.
- **Streaming/SSE**: the existing SSE transport (`api/stream.ts`
  frontend, whatever streams `ModelResponse` chunks today) is reused
  for `AgentEvent` chunks too — same wire mechanism, different
  event-shape on top of it. No new streaming transport.

### The `AIModel` row / `Chat.model_id` constraint

Two options, both viable, real trade-off between them — recommending
one, not deciding unilaterally since it's a schema decision:

**Option A (recommended): one placeholder `AIModel` row for ILA.**
Seed a single `models` row, e.g. `model_key="ila-agent"`,
`category` = a new `ModelCategory.AGENT` enum value (one new enum
value + one migration, same pattern as any category addition per
ADR 0007's own "Consequences" section — this is explicitly the
extension path that ADR already anticipated), `provider="ila-agent"`
(just a descriptive string column — nothing reads this and constructs
a `ModelProvider` from it; it's metadata, same as it is for Qwen rows
today). **This row is never registered in `ModelRegistry`.**
`ChatService`'s branch checks `chat.agent_key` (new nullable column,
see below) *before* ever calling `ModelRouter.route(chat.model.model_key)`
— so the fact that `ila-agent` isn't in the registry never gets
exercised as an error path; it's simply never looked up that way.
The row exists purely so `Chat.model_id`/`Usage.model_id` continue to
mean what they already mean (a valid FK), with zero schema change to
either of those two tables.

**Option B: make `model_id` nullable, add `agent_key`, add a
CHECK constraint that exactly one of the two is set.** Semantically
cleaner (no "fake model" row), but touches two existing tables'
nullability and requires updating every existing query that assumes
`Chat.model_id`/`Usage.model_id` is always present (repositories,
admin dashboards' usage-by-model reports) to handle the null case —
more surface area, more regression risk for something the instructions
explicitly ask to minimize.

**Recommendation: Option A.** It satisfies "avoid unnecessary changes"
more literally — `chats`/`usage_records` need exactly one new nullable
column (`agent_key`) each, not a nullability change to an existing
required column, and existing reporting queries keep working
unmodified since `model_id` is still always populated.

### Files/classes to modify (existing code)

Kept to the minimum that makes the branch possible — everything else
in the list from the instructions (`ModelRouter`, `QwenCoderProvider`,
`QwenNLPProvider`, `conversation_service.py`'s streaming/edit/revision
logic) is **not** touched:

| File | Change |
|---|---|
| `src/models/chat.py` | + nullable `agent_key: str \| None` column |
| `src/models/usage.py` | + nullable `agent_key: str \| None` column (mirrors chat.py, for usage rows attributable to an agent run rather than a direct model call) |
| `src/models/enums.py` | + `ModelCategory.AGENT` |
| `alembic/versions/` | one new migration: 2 columns + enum value + the one `ila-agent` seed row |
| `src/services/chat_service.py` | Not modified — chat title generation etc. is model/agent-agnostic already. |
| `src/services/conversation_service.py` | **Implemented for `create_chat` + `send_message` only** (new `_call_agent` branch mirroring `_reserve_call_release`). `edit_message`/`regenerate_message`/streaming variants are NOT yet agent-aware — deferred, same additive pattern applies when needed. Ownership/RBAC checks are unchanged and run before any branch. |
| `src/main.py` | + `agent_layer.bootstrap.register_default_agents(...)` call, alongside the existing `model_layer.bootstrap.register_default_providers(...)` call — same pattern, new line |
| `src/schemas/chat.py` | chat-creation request gains an optional `agent_key` alternative to `model_key` (mutually exclusive) |
| `frontend/src/api/types.ts`, `ModelInfo` | `category` gains `"AGENT"` as a possible value — `ModelSelector.tsx` needs **zero changes**, since it already renders whatever `GET /models` returns generically (verified by reading the component: it maps over `models`, keys off `model_key`/`category`/`display_name` with no Qwen-specific logic) |

### New files (agent layer)

Listed above under `src/agent_layer/`. Plus:
`backend/tests/unit/agent_layer/` — new test directory, mirrors
`tests/unit/test_model_layer.py`'s structure: a fake/mock
`AgentAdapter` (analogous to `MockProvider`) proves the registry +
branch logic end-to-end without needing real ILA code, so this part
is independently testable even before ILA's interface is finalized.

### Configuration changes

New env vars, same naming/loading convention as `QWEN_CODER_*`
(`backend/.env.example`):

```text
ILA_ENABLED=false            # default off — reversibility requirement
ILA_MODULE_PATH=              # import path or filesystem path to the ILA module
ILA_DEFAULT_MODEL_KEY=        # which registered model (qwen2.5-coder-7b, etc.)
                               # ILA calls by default, if it needs one
ILA_WORKSPACE_ENABLED=false    # separate flag — Web IDE can be off
                               # even if ILA text-only mode is on
```

Disabling (`ILA_ENABLED=false`, the default) means
`agent_layer.bootstrap.register_default_agents` registers nothing,
`AgentRegistry` is empty, the frontend's `GET /models` response
contains no `AGENT`-category entry, and `ModelSelector` shows exactly
what it shows today — this is the concrete mechanism behind "restore
existing behavior without code changes."

---

## Web IDE (§4–§6 of the request)

### Recommendation: reuse `code-server`, don't build an IDE

`code-server` (Coder's open-source, MIT-licensed, browser-hosted VS
Code) satisfies essentially every listed requirement out of the box:
file browsing/edit/create/delete/rename (real filesystem, not a
reimplementation), an integrated terminal, running commands, and
extension support. Building a custom Monaco-based IDE to get these
same capabilities would be substantially more code for a worse result
— this is the concrete case for "prefer reuse."

One licensing detail worth flagging now rather than discovering
later: Microsoft's official Extension **Marketplace** cannot be used
by non-Microsoft VS Code builds (their Marketplace ToS restricts this
to Microsoft's own product). `code-server` (and OpenVSCode Server, the
alternative) point at **Open VSX** (`open-vsx.org`) instead — an
open-source registry with most popular extensions, self-hostable if
an air-gapped/restricted environment is ever needed. This is the
correct, license-clean way to get "VS Code-compatible extensions,"
not a limitation of the chosen approach.

### Why not literally VS Code's "Remote-SSH"

The idea in the request — "Remote-SSH-style, but SSH handled by a
backend/workspace server, not the browser" — is exactly right as an
architecture *shape*, but VS Code's actual Remote-SSH extension and
its remote-side component are Microsoft-licensed for use with
Microsoft's own client, not freely embeddable in a custom web product.
The shape is achieved differently: `code-server` runs a full VS Code
server process **directly on the workspace machine** (no SSH-based
remoting protocol involved at the IDE layer at all) — the "SSH" part
of the architecture is how *our backend* reaches the workspace machine
to provision/manage that `code-server` process, not how the *IDE
itself* talks to files.

### Component responsibilities

```text
Browser
  |  HTTPS/WSS, platform JWT (same auth as chat)
  v
Backend (FastAPI) — new: workspace/proxy endpoints only
  |  authenticates + checks workspace ownership, then proxies bytes
  |  SSH (backend-held key, never sent to browser) to provision/
  |  reach the workspace machine
  v
Workspace machine (remote host from workspace info)
  - code-server process, bound to localhost/private interface only
    (never publicly routable)
  - launched with its working directory = the target folder from
    workspace info (this IS the path restriction — enforced by what
    directory the process is given, and by the OS user's own
    filesystem permissions, not by the backend reimplementing a
    virtual filesystem/ACL layer)
  - runs as an unprivileged, workspace-scoped OS user (or inside a
    per-workspace container) — this is the actual isolation boundary
    for file access, not something the backend re-enforces itself
```

**Resolved: credentials are shared/backend-held, not per-user.** SSH
access to workspace machines uses one backend-held key (or a small,
fixed set — one per machine/fleet), not a distinct credential per
user. The actual access boundary is **which folder** a session is
scoped to, not which OS account: the backend resolves "the folder
suggested by the backend" for a given ILA session/user and launches
that session's `code-server` with that exact directory as its
workspace root. A user never gets broader filesystem reach than the
one folder the backend hands them — enforced by what path
`code-server` is started against, same mechanism as before, now
confirmed as the actual design rather than one of two options.

**Resolved: terminal is disabled.** Not a UI-only toggle — VS Code
settings/product-config can hide the terminal panel, but that's
client-side and not trustworthy as the actual control. The real
enforcement is at the proxy layer this platform already owns:
`proxy.py` (below) recognizes `code-server`'s terminal-specific
WebSocket route and refuses to forward it (403), independent of
whatever the `code-server` UI shows. This also simplifies the earlier
open question about command-execution controls — with no terminal,
there is no general-purpose command execution to bound, so that
concern drops out of scope rather than needing a policy.

**Confirmed in scope, unchanged from `code-server` defaults:** file
create/delete/rename stays enabled in the editor's file explorer — no
proxy-layer restriction needed there, since it's already scoped to
the one allowed folder by the workspace-root argument above.

### New backend package: `src/agent_layer/workspace/`

```text
workspace_service.py    create/lookup a workspace record (host, auth
                          reference, target path) tied to an ILA
                          session; ownership-checked the same way
                          chats are (self-ownership pattern already
                          established, reused not reinvented)
ssh_manager.py            backend-side SSH client: connect using a
                          server-held key (see Credential handling),
                          ensure code-server is running on the target
                          host, establish a tunnel/local port-forward
                          to its bound port
proxy.py                   FastAPI routes that reverse-proxy
                          authenticated HTTP/WebSocket traffic from
                          the browser through to the tunneled
                          code-server port — this is the ONLY thing
                          the browser ever talks to; it never sees
                          host/port/credentials of the workspace
                          machine directly. Also where the terminal
                          WebSocket route is specifically denied
                          (403) — see "Resolved: terminal is
                          disabled" above; this is the actual security
                          control, not the code-server UI setting.
session_registry.py         tracks active tunnels (in-memory, or
                          Redis — already in the stack for rate
                          limiting, reusable here too if the backend
                          runs >1 worker process, same reasoning as
                          the rate limiter's own Redis requirement)
                          keyed by (user_id, workspace_id); idle
                          timeout tears the tunnel down
```

### Credential handling

- SSH private key(s) for workspace machines: stored server-side only,
  filesystem path referenced via config/env (same posture as
  `SECRET_KEY` today — not committed, not returned by any API).
  **Shared/backend-held, not per-user** (resolved above) — the access
  boundary is the target folder a session is scoped to, not a
  distinct OS identity per user. If/when this needs to scale beyond a
  small, fixed set of workspace machines, that calls for a real
  secrets manager (Vault, cloud provider's secrets service) — flagged
  as a deliberate later upgrade, not built prematurely.
- The key/credential **never** crosses into the browser or into any
  API response — the backend is the only thing that ever uses it.
- `code-server`'s own access (its `--auth` mechanism / a per-session
  token) is generated by the backend per session and only handed to
  the *proxy path*, not to the browser as a separate credential the
  frontend has to manage — from the browser's point of view, it's
  just talking to our own platform.

### Session lifecycle / timeouts

Idle timeout closes the SSH tunnel (and can optionally stop
`code-server` on the workspace machine to free resources); explicit
"end session" from the UI does the same immediately. Reconnecting
within an active workspace's lifetime re-establishes the tunnel
without re-provisioning `code-server` from scratch.

### Audit/logging

Session start/stop, user, workspace id, duration — logged through the
existing structured-logging convention (`core/logging.py`), same
posture as everywhere else in this codebase: never log terminal
keystroke content or file contents, only session-level metadata
(consistent with `SECURITY.md`'s existing "never log
request/response bodies" rule — this is the same principle applied to
a new surface, not a new rule).

---

## UI (§3 of the request)

- `ModelSelector.tsx`: **unchanged**, as established above — an
  `AGENT`-category entry from `GET /models` just renders like any
  other option, since the component already has no Qwen-specific
  logic.
- New, small: once the selected "model" is ILA (checked by
  `category === "AGENT"` or `model_key === "ila-agent"` — a one-line
  condition in `ChatView.tsx`/`Composer.tsx`, wherever the currently
  selected model is already read), render a "Open VS Code" button.
  Clicking it opens the workspace proxy path (§Web IDE) in a new tab
  or a side panel — implementation detail to settle in Phase 3, not
  architecturally significant either way.
- The button/action is explicitly **not** another entry in
  `ModelSelector` — it's a capability of the current ILA session, not
  a selectable model, matching the instruction directly.

---

## Data/control flow (one full request, ILA enabled)

```text
1. User selects "ILA" in ModelSelector (an AGENT-category entry)
2. Chat created with agent_key="ila-agent", model_id=<placeholder row>
   (chat_service.py's new branch — everything else in that function
   unchanged)
3. User sends a message
4. conversation_service.py's new branch: chat.agent_key is set ->
   AgentRegistry.get("ila-agent") -> ILAAgentAdapter.run/stream(...)
   (existing ownership/RBAC/quota checks already happened before
   this branch, unchanged)
5. ILAAgentAdapter calls into the real ILA module. If ILA needs an
   LLM call, it goes through the SAME ModelRouter instance
   ChatService already holds (injected, not re-instantiated) -> the
   same QwenCoderProvider/QwenNLPProvider as any normal chat
6. ILA's result (text + optional workspace_id) streamed back over
   the existing SSE transport as AgentEvent chunks
7. If a workspace is involved, frontend shows "Open VS Code" ->
   backend workspace/proxy endpoints (new) -> SSH-provisioned
   code-server on the remote workspace machine
```

## Risks and compatibility concerns

- **Schema change is the one irreversible-feeling part.** The new
  columns/enum value are additive and nullable, so existing rows/
  queries are unaffected — but once ILA chats exist in production,
  the `agent_key` column can't be casually dropped again. Mitigated
  by keeping it minimal (one column per table, Option A above) rather
  than a deeper schema redesign.
- **ILA's real interface is unknown to this design.** `agent_interface.py`
  and `ila_adapter.py` above describe the *shape* the adapter should
  have, not its final method signatures — those depend on what ILA's
  actual Python module exposes (sync/async, streaming or not, how it
  reports tool calls). This is the first blocker below.
- **Workspace/SSH subsystem is materially new infrastructure**, not a
  small addition — it's the single largest new risk surface in this
  proposal (credential handling, network exposure, session lifecycle).
  Recommend it lands as its own phase, after the text-only ILA path
  is working and reversible, not bundled into the same phase.
- **Multi-worker consideration**: `session_registry.py`'s in-memory
  option repeats the exact process-locality mistake already fixed
  once in this codebase (`RateLimitMiddleware`, see
  `docs/architecture/final-review.md`'s remediation note) if the
  backend ever runs `WEB_CONCURRENCY > 1` — recommend defaulting to
  the Redis-backed option from the start here rather than repeating
  that lesson a second time.

## Phased implementation plan

1. **Agent layer skeleton + reversibility, no real ILA yet.**
   `agent_interface.py`, `schemas.py`, `registry.py`, `bootstrap.py`
   (registers nothing while `ILA_ENABLED=false`), the two new columns
   + enum value + placeholder `AIModel` row migration, the two
   `chat_service.py`/`conversation_service.py` branches, a
   `FakeAgentAdapter` test double (mirrors `MockProvider`). Fully
   testable, fully reversible, zero real ILA code required yet —
   proves the seam the same way `MockProvider` proved the model layer
   in ADR 0007.
2. **Real `ILAAgentAdapter`**, once ILA's interface is inspected
   (blocker below). Wires the actual module in behind the adapter
   built in step 1.
3. **UI**: `AGENT` category surfaces in `ModelSelector` (no component
   change needed, per above), "Open VS Code" button gated on
   category, basic ILA chat UX.
4. **Workspace/Web IDE subsystem**: `code-server` provisioning,
   SSH manager, proxy endpoints, session registry — its own phase per
   the risk note above.
5. **Hardening**: idle-timeout tuning, audit logging review, and
   revisiting the credential-storage approach if usage grows past what
   file-based key storage comfortably supports.

## Blockers before Phase 1 can start writing `ila_adapter.py` for real

**Resolved.** ILA's interface: `ILA(**kwargs).main(query="")` — plain,
blocking Python class, no async/streaming. `ila_adapter.py` runs it
via `asyncio.to_thread` with a timeout; `constructor_kwargs` are
forwarded verbatim from config rather than guessed (see
`agent_layer/config.py`). Credential model: resolved above.

## Consequences

- Everything under `src/model_layer/` and the existing Qwen-only chat
  flow is provably unaffected by inspection: no file in that
  directory, nor `chat_service.py`/`conversation_service.py` beyond
  the two single, additive branches, needs to change for reasons
  other than "there is now a second kind of chat."
- Adding a second agent later is "implement `AgentAdapter`, register
  it" — the same shape ADR 0007 already established for models,
  deliberately mirrored here rather than inventing a different
  extension pattern for agents vs. models.
- The Web IDE subsystem is the one piece of this proposal that isn't
  a small, additive change — it's genuinely new infrastructure, and
  is scoped as its own phase for that reason.
