# Deployment

Reproducible procedure for deploying this system to development,
staging, and production. Complements `ARCHITECTURE.md` (how it's
built), `SECURITY.md` (what's protected), and `PERFORMANCE.md` (how it
scales) rather than repeating them.

## Architecture

```text
                    Users
                      |
                    HTTPS
                      |
                    Nginx
                      |
          +-----------+-----------+
          |                       |
      Frontend                 Python API
     (static SPA)                 |
                         +--------+--------+
                         |        |        |
                     PostgreSQL  (n/a)   Qwen (Coder / NLP)
```

Nginx terminates TLS and is the only publicly reachable process. It
serves the built frontend directly (static files) and reverse-proxies
`/api/` to the Python API. The API talks to Postgres and to the Qwen
model server(s) over the network — neither is reachable from outside
the deployment; see "Do not expose backend/model ports publicly" below.

There is a "(n/a)" where the brief's diagram shows a generic "Workers"
box: **this codebase has no separate background-worker process.**
Everything — including model calls — happens synchronously within a
single request's async event loop (see `services/chat_service.py`,
`services/conversation_service.py`). If a future phase adds one (e.g.
scheduled quota resets, batch usage aggregation), it belongs here as
its own documented process; today there is nothing to run.

## API process / worker process / model process

Three distinct process concepts, since Phase 12 asks for them to be
documented explicitly:

- **API process**: `gunicorn -c gunicorn.conf.py src.main:app`
  (`backend/gunicorn.conf.py`) — N worker processes, each running the
  full FastAPI app with its own async event loop and its own DB
  connection pool. This is the only process type this codebase
  actually runs in production. Horizontally scaled via
  `docker-compose.prod.yml`'s `deploy.replicas` (nginx round-robins
  across them — see `nginx/nginx.conf.template`'s `upstream
  python_api`).
- **Worker process**: does not exist in this codebase today (see
  above). Documented here so its absence is a deliberate, visible fact
  rather than a silent gap.
- **Model process**: Qwen Coder / Qwen NLP, each its own
  OpenAI-compatible inference server (vLLM, TGI, or similar), reached
  over HTTP via `QWEN_CODER_ENDPOINT_URL` / `QWEN_NLP_ENDPOINT_URL`
  (`backend/.env.example`). **Not built or run by this repository** —
  it's GPU-bound infrastructure that scales independently of the API
  tier; see `PERFORMANCE.md`, "API scalability vs. model inference
  scalability". `ModelRouter.acquire_slot()`
  (`backend/src/model_layer/router.py`) bounds how many concurrent
  requests the API process sends to each one, but does not run them.

## Nginx

`nginx/nginx.conf.template` (rendered per-environment by
`nginx/docker-entrypoint.sh`, which substitutes `__SERVER_NAME__` /
`__SSL_CERT_PATH__` / `__SSL_KEY_PATH__` / `__API_UPSTREAM__`) provides:

- Reverse proxy to the API (`location /api/`), static frontend
  (`location /`) with long-cache headers on hashed build assets and no
  caching on `index.html`.
- HTTPS-ready `server { listen 443 ssl http2; ... }` block, commented
  out until real certificates exist (uncomment at deploy time, or once
  `SSL_CERT_PATH`/`SSL_KEY_PATH` point at real files).
- SSE streaming support: `proxy_buffering off` on `/api/` so chat
  streaming reaches the client incrementally, generous
  `proxy_read_timeout`/`proxy_send_timeout` (300s — must stay ≥
  `QWEN_*_REQUEST_TIMEOUT_SECONDS` plus headroom).
- WebSocket upgrade support (conditional `Connection` header via the
  `map` block) — nothing in the app uses WebSockets today; this is
  forward compatibility, not active behavior.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`) — also set independently by the FastAPI app itself
  (`backend/src/main.py`) as defense-in-depth; see `SECURITY.md`.
- Request limits: `limit_req_zone` — 20r/s general, 5r/min on
  `/api/v1/auth/*` specifically. This is nginx's coarse first line of
  defense; the app's own `RateLimitMiddleware` and the audit-log-driven
  login lockout (`src/services/auth_service.py`) are what actually
  hold under sustained abuse or a restarted nginx — see `SECURITY.md`.

**Do not expose backend/model ports publicly**: the API container only
`expose`s (not `ports:`) 8000 in `docker-compose.prod.yml`, so it's
reachable from other containers on the compose network but not from
the host/internet — only nginx's 80/443 are published. The Qwen
endpoints are configured as internal hostnames
(`http://qwen-coder.internal:8001/v1` in `.env.production.example`) and
were never part of this compose stack to begin with.

## Python deployment

Production ASGI process: `backend/gunicorn.conf.py`, using
`uvicorn_worker.UvicornWorker` workers. Covers:

- **Multiple workers**: `WEB_CONCURRENCY` env var (default: `min(4,
  cpu_count)`). See `PERFORMANCE.md` bottleneck #2 before raising this
  — each worker gets its own DB pool
  (`DATABASE_POOL_SIZE`+`DATABASE_MAX_OVERFLOW` connections), so
  `workers × pool ≤ Postgres max_connections` or use PgBouncer.
- **Graceful shutdown**: `graceful_timeout` (default 30s) — in-flight
  requests, including long SSE streams, get time to finish on SIGTERM
  before a worker is killed. Orchestrators should send SIGTERM and wait
  at least this long before SIGKILL (Docker's default `stop_grace_period`
  is 10s — override it if using `docker stop` directly rather than
  compose's own shutdown handling).
- **Health checks**: `GET /api/v1/health` (liveness — is the process
  up) and `GET /api/v1/system/diagnostics` (readiness — is the
  database actually reachable; Developer/Owner-only, so an
  orchestrator's readiness probe needs a service-level bypass or
  should just use `/health` plus its own DB check). Both the Docker
  image (`HEALTHCHECK` in `backend/Dockerfile`) and
  `docker-compose.prod.yml`'s `healthcheck:` use `/health`. nginx also
  proxies `/healthz` → `/api/v1/health` for load balancers that expect
  a conventional path.
- **Environment configuration**: every setting is an env var
  (`backend/src/core/config.py`, `Settings`) — no config file to bake
  into an image. `backend/.env.example` documents every variable;
  `.env.staging.example` / `.env.production.example` (repo root) show
  the environment-specific subset that actually needs to differ.

## Database

- **Connection pooling**: `DATABASE_POOL_SIZE` (default 10) +
  `DATABASE_MAX_OVERFLOW` (default 20) per API worker process — see
  `backend/src/db/session.py`. Sizing guidance and the
  workers-vs-Postgres-max_connections math is in `PERFORMANCE.md`
  bottleneck #2; don't duplicate that reasoning here.
- **Migration process**: Alembic (`backend/alembic/`). Run `alembic
  upgrade head` as its own step *before* the API starts serving traffic
  — `docker-compose.prod.yml`'s `migrate` service does this and the
  `backend` service `depends_on: migrate: condition:
  service_completed_successfully`, so a rolling deploy never has
  workers starting against a schema mid-migration. Never run migrations
  from inside multiple concurrently-starting API replicas — Alembic
  isn't designed for concurrent `upgrade head` races.
  ```bash
  # Roll forward
  alembic upgrade head
  # Roll back one revision (emergency only — verify the downgrade()
  # for the specific revision actually exists and is safe; not every
  # migration in alembic/versions/ has been written with a safe
  # downgrade path for a system already holding production data)
  alembic downgrade -1
  # See pending migrations without applying them
  alembic upgrade head --sql
  ```
- **Backup**: `pg_dump` on a schedule (e.g. via the managed database
  provider's automated backups in staging/production — see
  `.env.production.example`'s comment recommending managed Postgres —
  or a cron'd `pg_dump -Fc` job pointed at object storage if
  self-hosting via the commented-out `postgres:` service in
  `docker-compose.prod.yml`).
  ```bash
  pg_dump -Fc --dbname="$DATABASE_URL" -f "backup_$(date +%Y%m%d_%H%M%S).dump"
  ```
- **Restore**:
  ```bash
  pg_restore --clean --if-exists --dbname="$DATABASE_URL" backup_20260101_000000.dump
  ```
  Always restore into a fresh/isolated database first and run the
  application's test suite against it before pointing production
  traffic at a restored database — a syntactically successful restore
  doesn't guarantee no data loss occurred in the window between the
  backup and the incident it's recovering from.
- **Production credentials**: never in version control. `.env.example`,
  `.env.staging.example`, `.env.production.example` are templates with
  placeholder values only. Real `SECRET_KEY`/`DATABASE_URL` values come
  from the deployment platform's secret store (e.g. Docker
  secrets, a cloud provider's secrets manager, or CI/CD-injected env
  vars at deploy time) and are passed to `docker compose --env-file`
  or the orchestrator's own secret-mounting mechanism — this repo has
  no code path that reads secrets from anywhere other than environment
  variables (`pydantic-settings`, `backend/src/core/config.py`), so
  "inject via env var" is the only integration point any secrets
  manager needs to support.

## Deployment environments

| | Development | Staging | Production |
|---|---|---|---|
| Compose file | `docker-compose.yml` | `docker-compose.prod.yml` | `docker-compose.prod.yml` |
| Env file | `backend/.env` (optional) | `.env.staging` | `.env.production` |
| `DEBUG` | `true` | `false` | `false` |
| TLS | none (Vite dev server, plain HTTP) | real cert, real domain | real cert, real domain |
| Backend replicas | 1 (with `--reload`) | 1 | 4 (tune to load — see `PERFORMANCE.md`) |
| Database | containerized Postgres | managed/shared instance recommended | managed instance, automated backups |
| Qwen | optional / often disabled | optional, can be smaller/shared | required, sized for real traffic |
| Rate limits | app default (60/min) | same as production | same as app default, tune per observed traffic |

Staging exists specifically to catch problems (migrations, config
drift, real request volume) that a local dev environment can't
surface, so it intentionally mirrors production's topology
(`docker-compose.prod.yml`, same Dockerfiles) rather than being a
scaled-down variant of `docker-compose.yml`.

## Reproducible deployment procedure

```bash
# 1. Clone and configure
git clone <repo-url> && cd ai-platform-2
cp .env.production.example .env.production   # or .env.staging.example
# Fill in SECRET_KEY, DATABASE_URL, SERVER_NAME, QWEN_*_ENDPOINT_URL,
# CORS_ALLOW_ORIGINS with real values — see "Production credentials" above.

# 2. Provision TLS certificates
mkdir -p ssl/production
# Place fullchain.pem / privkey.pem there (e.g. via certbot), matching
# SSL_CERT_DIR / SSL_CERT_PATH / SSL_KEY_PATH in .env.production.

# 3. Build images
docker compose -f docker-compose.prod.yml --env-file .env.production build

# 4. Run migrations (one-shot, before traffic is routed)
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm migrate

# 5. Start the stack
docker compose -f docker-compose.prod.yml --env-file .env.production up -d

# 6. Verify
curl -f https://<SERVER_NAME>/healthz
docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend

# 7. Rolling update for a new release
docker compose -f docker-compose.prod.yml --env-file .env.production build backend
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm migrate
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --no-deps backend
```

Step 7's `up -d --no-deps backend` recreates only the backend
service's replicas (nginx and the DB connection are untouched); each
old worker gets `graceful_timeout` (30s) to finish in-flight requests
before being replaced — see "Python deployment" above.

## What this does not cover

- Provisioning the Qwen inference server(s) themselves (GPU
  provisioning, model weights, vLLM/TGI configuration) — out of scope
  for this repository; see "API process / worker process / model
  process" above for why.
- A CI/CD pipeline that automates steps 3–7 — this document describes
  the manual procedure any pipeline should encode, not the pipeline
  itself (already flagged as a planned item in `SECURITY.md`).
- Multi-region/DR topology — the architecture above is single-region;
  extending it is a capacity-planning exercise for whoever operates a
  specific production deployment, not a code change here.
