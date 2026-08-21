# Developer Guide

## Architecture

Full details in `ARCHITECTURE.md`; the short version:

```
Nginx -> FastAPI (API process) -> PostgreSQL
                                -> ModelRouter -> ModelProvider -> Qwen (or other backend, over HTTP)
```

Layering (see `ARCHITECTURE.md` for the enforced import direction):
`api/` (routers) -> `services/` (business logic) -> `repositories/`
(data access) -> `models/` (SQLAlchemy ORM). `model_layer/` is a
parallel, independent stack the chat service depends on but which
depends on nothing above it — see "Model integration" below and ADR
0007.

## Model integration

Everything above `ModelRouter` only ever sees the `ModelProvider`
interface (`src/model_layer/provider_interface.py`) — no application
code checks `if model_key == "..."`. Concretely:

- `ModelRequest`/`ModelResponse`/`StreamingChunk`
  (`src/model_layer/schemas.py`) are provider-agnostic — a provider
  translates them to/from whatever its actual backend speaks.
- `ModelRegistry` (`src/model_layer/registry.py`) is the in-memory
  `model_key -> provider` index, built at startup
  (`src/model_layer/bootstrap.py`).
- `ModelRouter` (`src/model_layer/router.py`) resolves a `model_key`
  to a live provider and (as of Phase 11) bounds concurrent in-flight
  requests per model via `acquire_slot()`.
- The only concrete provider today is `QwenProvider`
  (`src/model_layer/providers/qwen/`), an HTTP client against an
  OpenAI-compatible endpoint. Nothing outside `providers/qwen/` and
  `bootstrap.py` imports it directly (see the module docstring in
  `provider_interface.py`).

## Logs

Structured JSON per request (`RequestLoggingMiddleware`,
`src/core/middleware.py`): timestamp, request_id, user_id, endpoint,
model (when applicable), duration_ms, status, error_type. Never
includes prompt/response content by construction — there's no code
path that logs a request/response body. View recent entries via `GET
/system/logs` (Developer dashboard) or directly in stdout/stderr if
running locally (`LOG_JSON=false` in `.env` for human-readable output
during development).

## Debugging

- `GET /system/diagnostics` — is the database reachable, process
  uptime, server time.
- `GET /system/performance` — request counts by status class, average
  response time; useful for spotting a specific endpoint degrading.
- `X-Request-ID` response header — correlates a specific browser
  request to its structured log line.
- Local dev: `DATABASE_ECHO=true` in `.env` prints every SQL statement
  SQLAlchemy issues, useful for N+1 query hunting.
- A `model_request_queued` log entry means a request had to wait for a
  concurrency slot at `ModelRouter.acquire_slot()` — see
  `PERFORMANCE.md` if you see many of these.

## Testing

```bash
cd backend
pip install -r requirements.txt --break-system-packages
pytest                          # unit + integration (needs Postgres; see tests/conftest.py)
pytest tests/unit               # no DB needed
SKIP_PG_TESTS=1 pytest          # skip everything requiring Postgres
```

```bash
cd frontend
npm install
npm run build                   # tsc --noEmit + vite build; catches type errors
npm run test:e2e                # Playwright — needs the full stack running; see tests/e2e/README.md
```

Load testing: `backend/perf/locustfile.py` — see `PERFORMANCE.md`.

## Adding a model

To add a new Qwen deployment (different size, different endpoint):
1. Add its config to `.env` (new `QWEN_*_ENDPOINT_URL` etc., or reuse
   the existing `QWEN_CODER_*`/`QWEN_NLP_*` vars if replacing one).
2. Seed a row in the `models` table (see
   `alembic/versions/..._seed_initial_qwen_models.py` for the pattern)
   or create it via `POST /admin/models` (Owner only).
3. No router, service, or persistence-layer code changes needed.

To add an entirely different backend (Llama, Mistral, a remote API):
1. Implement `ModelProvider` (`src/model_layer/provider_interface.py`)
   in a new module under `src/model_layer/providers/<name>/` —
   `generate()`, `stream()`, `health_check()`, `capabilities`.
2. Register it in `src/model_layer/bootstrap.py` alongside the
   existing Qwen registration calls.
3. Seed/create its `models` row the same way as above.

Nothing in `ChatService`, `ConversationService`, the API routers, or
the persistence layer changes for either case — see the Final
Architecture Check in `docs/architecture/final-review.md` for the
fuller reasoning, including where this genuinely does need new code
(tool-calling orchestration, embeddings).
