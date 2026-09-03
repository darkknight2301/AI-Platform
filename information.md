# information.md — Repository Map

Quick orientation for this codebase: what each top-level folder is,
what each backend layer does, and which file to open for a given kind
of change. Not a replacement for `ARCHITECTURE.md` (design rationale)
or the ADRs (`docs/adr/`, individual decisions) — this is the "where
do I look" index; those are the "why" documents.

---

## Top-level layout

```text
.
├── backend/            Python/FastAPI API server
├── frontend/            React/TypeScript SPA
├── nginx/                Reverse proxy config + Docker image
├── docs/                  Design docs, ADRs, per-role user guides
├── docker-compose.yml               Dev deployment (Docker)
├── docker-compose.prod.yml           Staging/prod deployment (Docker)
├── README.md                          Manual (non-Docker) deployment guide
├── ARCHITECTURE.md, SECURITY.md,
│   PERFORMANCE.md, DEPLOYMENT.md      Cross-cutting design/ops docs
└── .env.production.example,
    .env.staging.example               Root-level Docker Compose env templates
```

`README.md` and `DEPLOYMENT.md` are two different deployment guides
for the same application — manual/bare-metal vs. Docker, respectively
(see `README.md` §26 for how they relate). Application source code
never differs between the two.

---

## `backend/` — Python / FastAPI

```text
backend/
├── src/                   application source (see below)
├── alembic/               database migrations (schema source of truth)
├── tests/                 unit + integration tests
├── scripts/               operational scripts (not application code)
├── perf/                  load-testing (Locust) and one-off seed scripts
├── requirements.txt       what production actually installs
├── requirements-dev.txt   + pytest/httpx/aiosqlite, for running tests
├── gunicorn.conf.py       production process/worker config
├── pyproject.toml         pytest + ruff config
├── alembic.ini            Alembic config (points at alembic/)
├── .env.example           source of truth for every env var this app reads
└── Dockerfile
```

### `backend/src/` — layers, in dependency order

```text
main.py            composition root: builds the FastAPI app, wires
                    middleware, registers model providers at startup
core/               framework-level concerns, no business logic
  config.py           Settings (pydantic-settings, reads .env)
  security.py         password hashing, JWT issue/verify
  middleware.py        request logging, rate limiting, request-ID
  logging.py           structured JSON logging setup
db/                 SQLAlchemy engine/session plumbing only
models/             SQLAlchemy ORM table definitions (one file per
                    entity: user.py, chat.py, message.py, etc.) +
                    enums.py (Role, ChatStatus, MessageRole, ...)
repositories/       ONLY layer that writes SQLAlchemy queries — one
                    per entity, mirrors models/
services/           business logic; depends on repositories, never on
                    FastAPI/HTTP concepts directly
  auth_service.py       login, registration, session/lockout logic
  chat_service.py        chat lifecycle orchestration
  conversation_service.py message send/edit/streaming orchestration,
                           ownership enforcement (see docstring)
  quota_service.py         token/chat-count quota checks (advisory-lock
                            based, concurrency-safe — see ADR 0010)
  user_service.py           user/approval management
auth/               RBAC dependency chokepoint (require_min_role,
                    require_roles, can_manage_group) — see auth/README.md
model_layer/        provider-agnostic model abstraction (see below)
agent_layer/         orchestration/agent abstraction — ILA, and the
                    Web IDE subsystem. Deliberately separate from
                    model_layer/ — an agent is NOT a model (see ADR
                    0012). Off by default (ILA_ENABLED=false).
schemas/            Pydantic request/response models (API contracts,
                    distinct from models/'s DB tables)
api/v1/              FastAPI routers — HTTP layer only, delegates to
                    services/, never contains business logic itself
  routers/             one file per resource: auth, users, chats,
                       messages, models, system (diagnostics/admin
                       ops), admin (approvals, audit log)
  deps.py              shared FastAPI dependencies (get_db, get_current_user)
  error_mapping.py     exception → HTTP status/response mapping
workers/            reserved for a future phase; currently empty — see
                    README.md §12, there is no background worker today
```

**Rule enforced throughout:** `api/` → `services/` → `repositories/` →
`models/`, one direction only. `services/` never imports from `api/`;
`repositories/` never imports from `services/`.

### `backend/src/model_layer/` — the model abstraction

```text
provider_interface.py   ModelProvider ABC every provider implements —
                         this is the ONLY contract the rest of the app
                         depends on (see ADR 0007)
schemas.py               ModelRequest/ModelResponse/ModelMessage — the
                          provider-agnostic request/response shape
errors.py                 provider-agnostic exception hierarchy
registry.py                ModelRegistry — model_key -> provider lookup
router.py                   ModelRouter — category -> provider routing +
                             per-model concurrency cap
bootstrap.py                 composition: reads QWEN_*_ENABLED, builds
                              and registers whichever providers are on
providers/
  qwen/                       the ONLY place that knows anything
                              Qwen-specific (see ADR 0008)
    config.py                    QwenProviderConfig, env-var loading
    provider.py                   QwenProvider — OpenAI-compatible HTTP
                                   client (streaming, error mapping);
                                   model-agnostic at the HTTP-client
                                   level, reused by both subclasses below
    local_providers.py             QwenCoderProvider / QwenNLPProvider
                                    — thin per-model subclasses fixing
                                    model_key/category/display_name;
                                    talk to a local vLLM server process
                                    (see docs/model-serving.md)
  mock_provider.py               test-only fake provider (no network)
```

To add a new model provider: implement `ModelProvider`
(`provider_interface.py`), register it in `bootstrap.py`. Nothing else
in the codebase needs to change — that's the point of this layer.

### `backend/src/agent_layer/` — the agent abstraction (Model vs. Agent)

A **model** (Qwen Coder/NLP) answers one request with text via
`ModelProvider`. An **agent** (ILA) orchestrates models, tools, and a
vector DB/knowledge base to produce engineering output, and does NOT
implement `ModelProvider` — see ADR 0012 for why forcing that
distinction into one interface would be wrong.

```text
agent_interface.py   AgentAdapter ABC — the only contract, deliberately
                      smaller than ModelProvider (see its docstring)
schemas.py             AgentRequest/AgentResult/ILAGenerateParams —
                       ILA's generate() takes 7 fixed positional args
                       (query, mode, function_name, step,
                       test_case_desc, overwrite_step, output_file);
                       ILAGenerateParams is the typed carrier for the
                       six of those beyond query, required end-to-end
                       from SendMessageRequest.ila through to the call
registry.py             AgentRegistry — agent_key -> AgentAdapter,
                        structurally mirrors ModelRegistry
bootstrap.py             registers ILA iff ILA_ENABLED=true; also
                          keeps the placeholder AIModel row's
                          is_enabled in sync so a disabled agent
                          doesn't appear selectable in GET /models
config.py                  ILA_CHUNK_PATH/VECTOR_DB_PATH/ARTIFACTS_DIR/
                            WORKSPACE_DIR env vars -> ILA's constructor
                            kwargs; ILA_DEFAULT_MODE/OVERWRITE_STEP
adapters/
  ila_adapter.py             imports `from src.ila import ILA`
                              directly (fixed, first-party module —
                              NOT dynamically loaded) and calls
                              .generate(...) via asyncio.to_thread
                              (blocking call, timeout-guarded)
  fake_adapter.py             test double, no real ILA needed
workspace/                   the Web IDE subsystem — code-server
                             provisioning over backend-held SSH,
                             cookie-ticket browser auth, terminal
                             disabled at the proxy layer. See
                             docs/adr/0012-*.md, "§Web IDE"
```

`backend/src/ila/` itself (ILA's actual implementation) is not part
of this platform's codebase and was not created by this integration —
`ila_adapter.py` only imports it; it must be present in a given
deployment for `ILA_ENABLED=true` to actually work.

### `backend/alembic/versions/` — migrations, in order applied

```text
ce97266fb9cb_create_initial_schema.py           base schema
bea116010b54_add_auth_sessions.py                revocable-JWT sessions
d75afe937669_add_message_revision_tracking.py    message edit history
bdeda3f7a191_seed_initial_qwen_models.py         seeds the 2 model rows
                                                  the chat API expects
                                                  (do not skip)
86422d485a64_add_quota_overrides_and_reservations.py  quota system
bcacac32a666_fix_last_login_at_timezone.py       bugfix migration
```

### `backend/tests/`

```text
unit/          fast, no DB/network — one file roughly per src/ module
integration/   exercise routers end-to-end via httpx.AsyncClient
               against a real (test) DB — see conftest.py's fixtures
conftest.py     shared fixtures: async_client, DB setup/teardown
```

`backend/perf/locustfile.py` is a load-testing scenario, not a unit
test — run separately (Locust), not part of `pytest`.

---

## `frontend/` — React / TypeScript / Vite

```text
frontend/
├── src/
│   ├── main.tsx, App.tsx      entry point, routing shell
│   ├── context/AuthContext.tsx  auth/session state, app-wide
│   ├── api/                    one file per backend resource, all
│   │                            HTTP calls go through here — nothing
│   │                            in components/pages calls fetch directly
│   │   client.ts                  base fetch wrapper (auth header, base URL)
│   │   stream.ts                   SSE streaming client for chat
│   │   auth.ts, chats.ts, quota.ts,
│   │   admin.ts, manager.ts, system.ts
│   ├── components/                reusable UI pieces (ChatView,
│   │   dashboard/                  Composer, ModelSelector, Sidebar,
│   │                                per-role dashboard widgets)
│   └── pages/                     one per route (ChatPage, LoginPage,
│                                    RegisterPage, and one dashboard
│                                    page per role: Owner/Manager/
│                                    Developer)
├── tests/e2e/                    Playwright specs
├── vite.config.ts, tsconfig.json
├── package.json                   React + Vite + react-markdown +
│                                    lucide-react; no state-management
│                                    library beyond React context
└── .env.example                   VITE_API_BASE_URL only — baked in
                                     at build time, not read at runtime
```

Frontend never calls the backend's `/api/` routes directly from
components — always through `src/api/*.ts`, which is also where you'd
add a new endpoint's client function.

---

## `nginx/`

```text
nginx.conf.template   full http{} config (not a sites-available
                       snippet); serves the built frontend + reverse-
                       proxies /api/ to the backend; has SSE-streaming-
                       friendly settings (proxy_buffering off) already
docker-entrypoint.sh   substitutes __SERVER_NAME__ etc. placeholders
                       at container start (Docker path only — the
                       manual README.md does this with sed instead)
Dockerfile
```

---

## `docs/`

```text
adr/                one Architecture Decision Record per major choice
                    — read these for "why", not "what"
api/README.md         API contract reference
architecture/          ARCHITECTURE.md's companion + final-review.md
                       (honest post-Phase-13 self-assessment: what's
                       implemented vs. what's actually been executed)
model-serving.md        local vLLM model-server setup (systemd units,
                        GPU sizing, dependency isolation)
{owner,manager,developer,user}-guide/README.md
                          per-role usage docs (what each role can
                          actually do in the app)
troubleshooting/README.md  operational troubleshooting reference
```

---

## Root-level docs — which one to open

| Question | File |
|---|---|
| "How do I deploy this without Docker?" | `README.md` |
| "How do I deploy this with Docker?" | `DEPLOYMENT.md` |
| "Why is X built this way?" | `ARCHITECTURE.md`, `docs/adr/` |
| "What are the security controls / trust boundaries?" | `SECURITY.md` |
| "What are the known scaling limits?" | `PERFORMANCE.md` |
| "Is this actually production-ready?" | `docs/architecture/final-review.md` |
| "How do I run/configure the local Qwen models?" | `docs/model-serving.md` |
| "How does ILA (the agent) integrate, and how is it different from a model?" | `docs/adr/0012-ila-agent-and-web-ide-integration.md` |
| "What can a Manager/Owner/Developer/User actually do?" | `docs/{role}-guide/README.md` |
