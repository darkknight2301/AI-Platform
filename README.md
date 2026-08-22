# AI Platform — Manual Deployment Guide (No Docker)

This is the single source of truth for deploying and running the
complete application **manually, without Docker**, on a Linux host —
for local development, or for a bare-metal/VM production deployment.

**Application status:** all 13 development phases are complete
(auth/RBAC, model abstraction, Qwen integration, chat backend with
streaming/revisions, quotas, chat frontend, admin dashboards,
observability/security hardening, nginx + production deployment
tooling). See `ARCHITECTURE.md` for the full design and
[`docs/architecture/final-review.md`](./docs/architecture/final-review.md)
for an honest account of what's implemented vs. what's actually been
executed (short version: written and reviewed, but no test in this
repository — backend, frontend, or integration — has ever been run in
any build environment, because none of them had network access or a
live database/browser). This README does not change that; it only
gets the application running.

This repository is normally deployed via Docker (`docker-compose.yml`
for development, `docker-compose.prod.yml` for staging/production —
see `DEPLOYMENT.md` for that path). **Docker is not required.**
Everything Docker does here — running Python, Postgres, Redis, and
Nginx as isolated processes — has a direct manual equivalent on a
Linux host, documented below. Nothing in the application itself
changes between the two deployment methods; this README does not
modify any source code, only how the same code is installed and run.
See §29 for the mapping between the two.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Deployment Directory & User](#3-deployment-directory--user)
4. [Source Code Installation](#4-source-code-installation)
5. [Python Environment](#5-python-environment)
6. [Environment Configuration](#6-environment-configuration)
7. [PostgreSQL Installation](#7-postgresql-installation)
8. [Database Migration](#8-database-migration)
9. [Redis (Optional — Multi-Worker Rate Limiting)](#9-redis-optional--multi-worker-rate-limiting)
10. [Model Deployment (Qwen)](#10-model-deployment-qwen)
11. [Backend Startup](#11-backend-startup)
12. [Background Workers](#12-background-workers)
13. [Frontend Deployment](#13-frontend-deployment)
14. [Nginx Installation & Configuration](#14-nginx-installation--configuration)
15. [HTTPS](#15-https)
16. [systemd Services](#16-systemd-services)
17. [Startup Order](#17-startup-order)
18. [Health Checks](#18-health-checks)
19. [Logging](#19-logging)
20. [Troubleshooting](#20-troubleshooting)
21. [Deployment Validation Checklist](#21-deployment-validation-checklist)
22. [Upgrade Procedure](#22-upgrade-procedure)
23. [Rollback Procedure](#23-rollback-procedure)
24. [Backup & Recovery](#24-backup--recovery)
25. [Security Checklist](#25-security-checklist)
26. [Docker vs. Manual Deployment](#26-docker-vs-manual-deployment)

---

## 1. Overview

The application has three components that run as processes, plus one
external dependency this repository does not build or run:

- **Backend** — Python 3.11 / FastAPI, served in production by
  Gunicorn with Uvicorn workers (`backend/gunicorn.conf.py`). Owns all
  business logic, auth/RBAC, quotas, and the chat/streaming API.
- **Frontend** — React + TypeScript, built by Vite into a static SPA
  bundle (`frontend/dist`). Not a running process in production — it
  is served as static files by Nginx.
- **Nginx** — terminates TLS, serves the built frontend, and
  reverse-proxies `/api/` to the backend. The only publicly reachable
  process.
- **PostgreSQL** — the application's only database. Managed entirely
  through Alembic migrations (`backend/alembic/`).
- **Qwen model server(s)** — one dedicated vLLM process per model,
  run locally on this backend host using pre-downloaded weights (no
  Ollama, no third-party API). Full setup in §10 and
  `docs/model-serving.md`. If not yet configured, the application
  still starts and runs fully — chat just has no model to route to
  until `QWEN_CODER_ENABLED`/`QWEN_NLP_ENABLED` point at a running
  local server.
- **Redis** — optional. Only needed if you run more than one backend
  worker process (see §9); the application does not use Redis for
  anything else.

There is **no background-worker process** in this codebase (no
Celery/RQ/APScheduler/queue consumer). Everything, including model
calls, happens synchronously inside a request's async event loop
(`backend/src/services/chat_service.py`,
`backend/src/services/conversation_service.py`). This is confirmed in
`DEPLOYMENT.md` and `backend/src/workers/` (present but empty, for a
later phase). Section 12 exists only to state this explicitly.

```text
                         Users
                           |
                         HTTPS
                           |
                         Nginx  (:80 / :443 — the only public process)
                           |
              +------------+-------------+
              |                          |
     Frontend (static SPA,       Python Backend (Gunicorn +
      served by Nginx from        Uvicorn workers, :8000,
      frontend/dist)              reachable only via Nginx)
                                          |
                          +---------------+----------------+
                          |               |                |
                     PostgreSQL     Redis (optional,   Qwen Coder /
                     (:5432)        multi-worker         Qwen NLP
                                     rate limiting,     (external,
                                     :6379)             not run by
                                                         this repo)
```

---

## 2. Prerequisites

The repository does not pin an exact Ubuntu version anywhere. The
Docker images it does build from are Debian "bookworm"-based
(`python:3.11-slim`, `node:20-slim`), so **Ubuntu 22.04 LTS or 24.04
LTS** is the recommended target — both are close enough to that base
that no application-specific adjustment is needed. `<VALUE_TO_CONFIGURE>`
if your organization mandates a different LTS release; nothing here
depends on an Ubuntu-specific feature.

| Requirement | Version / spec | Source |
|---|---|---|
| OS | Ubuntu 22.04 LTS or 24.04 LTS (recommended, not pinned by the repo) | Docker base images |
| Python | 3.11+ | `backend/pyproject.toml` (`requires-python = ">=3.11"`), `backend/Dockerfile` |
| Node.js | 20.x | `frontend/Dockerfile`, `nginx/Dockerfile` |
| PostgreSQL | 14+ (dev container image is 16; no exact production minimum is stated beyond 14+) | existing `README.md` prerequisite, `docker-compose.yml`'s `postgres:16-alpine` |
| Nginx | any version supporting `map`, `limit_req_zone`, `proxy_buffering off` (Ubuntu 22.04/24.04's packaged Nginx — 1.18+/1.24+ — satisfies this) | `nginx/nginx.conf.template` |
| Redis | 7.x (only if running >1 backend worker process — see §9) | `docker-compose.prod.yml`'s `redis:7-alpine` |
| Git | any recent version | — |
| CPU / RAM | not specified by the repository | `<VALUE_TO_CONFIGURE>` — size for your expected load; see `PERFORMANCE.md` for the worker/DB-pool sizing math once you have a `WEB_CONCURRENCY` figure in mind |
| GPU / CUDA | Required if running the local Qwen model server(s) (§10) — not required for the backend/frontend/Nginx/Postgres themselves | `docs/model-serving.md` |

Required ports (bind/expose only what you actually need reachable —
see §25):

| Port | Service | Public? |
|---|---|---|
| 80 / 443 | Nginx | Yes |
| 8000 | Backend (Gunicorn) | **No** — bind to `127.0.0.1` only; Nginx is the sole path in |
| 5432 | PostgreSQL | No |
| 6379 | Redis (if used) | No |
| 8001 / 8002 | Qwen Coder / Qwen NLP defaults (external servers, not part of this host's deployment unless you also host them here) | No |

Install base OS packages:

```bash
sudo apt update
sudo apt install -y \
    software-properties-common curl git build-essential \
    python3.11 python3.11-venv python3.11-dev \
    libpq-dev \
    postgresql postgresql-contrib \
    nginx \
    ca-certificates gnupg
```

`libpq-dev` and `build-essential` mirror `backend/Dockerfile`'s
`gcc libpq-dev` — kept in case `asyncpg`/`bcrypt` need to compile
from source on your target architecture rather than using a prebuilt
wheel.

Install Node.js 20 (Ubuntu's default `apt` package is usually older;
use NodeSource):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version   # expect v20.x
```

---

## 3. Deployment Directory & User

Docker Component → Manual Equivalent:

```text
Docker's `appuser` (uid 1000, backend/Dockerfile)
        ↓
A dedicated, non-login system user that owns and runs the app

Docker's ephemeral container filesystem + named volumes
        ↓
A fixed directory tree under /opt, owned by that user
```

```bash
sudo useradd --system --create-home --home-dir /opt/ai-platform --shell /usr/sbin/nologin aiplatform

sudo mkdir -p /opt/ai-platform/{app,venv,logs,ssl,backups}
sudo chown -R aiplatform:aiplatform /opt/ai-platform
```

```text
/opt/ai-platform/
├── app/            application source (this repository)
│   ├── backend/
│   └── frontend/
├── venv/           backend Python virtual environment
├── logs/           optional: only if you redirect logs here instead
│                   of journald (see §19 — journald is the default
│                   and recommended location)
├── ssl/            TLS certificate material for Nginx (§15)
└── backups/        database backup archives (§24)
```

The application never needs to run as root — Gunicorn, and Nginx's
worker processes, both run as unprivileged users (§16).

---

## 4. Source Code Installation

```bash
sudo -u aiplatform git clone <REPOSITORY_URL> /opt/ai-platform/app
cd /opt/ai-platform/app
sudo -u aiplatform git checkout <BRANCH_OR_TAG>   # e.g. main, or a release tag
```

`<REPOSITORY_URL>` and `<BRANCH_OR_TAG>` are environment-specific —
use whatever your team's Git remote and release process actually are.
If the remote requires authentication, configure Git credentials for
the `aiplatform` user before cloning (SSH deploy key or a credential
helper) rather than embedding a token in the URL.

All commands below assume the working directory is
`/opt/ai-platform/app` unless otherwise noted.

---

## 5. Python Environment

```text
Docker: FROM python:3.11-slim, pip install -r requirements.txt
        ↓
System Python 3.11 + a virtualenv + the same requirements.txt
```

```bash
cd /opt/ai-platform/app/backend
sudo -u aiplatform python3.11 --version        # expect 3.11.x

sudo -u aiplatform python3.11 -m venv /opt/ai-platform/venv
source /opt/ai-platform/venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

`backend/requirements.txt` is what `backend/Dockerfile` installs and
is what production actually runs. There is also
`backend/requirements-dev.txt` (`-r requirements.txt` plus `pytest`,
`pytest-asyncio`, `httpx`, `aiosqlite`) — install that instead **only**
if you intend to run the test suite on this machine:

```bash
pip install -r requirements-dev.txt
```

`redis` is listed in `requirements.txt` but only imported when
`RATE_LIMIT_REDIS_URL` is set (see §9) — installing it unconditionally
is harmless and matches what the Docker image does.

---

## 6. Environment Configuration

`backend/.env.example` is the source of truth. Copy it and fill in
real values — **never commit the resulting file**:

```bash
sudo -u aiplatform cp /opt/ai-platform/app/backend/.env.example /opt/ai-platform/app/backend/.env
```

Generate `SECRET_KEY` (and any other secret) with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

### Required

| Variable | Purpose | Example |
|---|---|---|
| `SECRET_KEY` | JWT signing key. Must differ per environment — a shared key across dev/staging/prod means a leaked staging token is a valid production token. | `<generate-with-command-above>` |
| `DATABASE_URL` | Async SQLAlchemy/Postgres connection string | `postgresql+asyncpg://app_user:<secure-password>@localhost:5432/app_db` |
| `CORS_ALLOW_ORIGINS` | Origins allowed to call the API from a browser | `https://<YOUR_DOMAIN>` |

### Optional / has a safe default

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `AI Platform API` | Display name only |
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` \| `test` — controls `DEBUG` behavior and is reported by `/api/v1/health` |
| `DEBUG` | `true` (dev) / must be `false` in production | Never `true` in production |
| `API_V1_PREFIX` | `/api/v1` | API route prefix |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT lifetime |
| `ALGORITHM` | `HS256` | JWT signing algorithm |
| `DATABASE_POOL_SIZE` | `10` | Per-worker-process DB pool size — see the sizing math in `PERFORMANCE.md` before raising `WEB_CONCURRENCY` |
| `DATABASE_MAX_OVERFLOW` | `20` | Per-worker-process pool overflow |
| `DATABASE_ECHO` | `false` | SQL query logging — dev/debug only |
| `LOG_LEVEL` | `INFO` | — |
| `LOG_JSON` | `true` | Structured JSON logs; set `false` for human-readable local dev logs |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | Per-client request budget, `RateLimitMiddleware` |
| `TRUST_PROXY_HEADERS` | `false` | Set `true` **only** if Gunicorn is reachable exclusively through Nginx (see §14/§25) — otherwise a client can forge `X-Forwarded-For` and bypass rate limiting |
| `RATE_LIMIT_REDIS_URL` | unset | See §9 — required for correct rate limiting once you run more than one Gunicorn worker process |
| `DEFAULT_MAX_ACTIVE_CHATS` | `20` | Quota default |
| `DEFAULT_TOKEN_QUOTA` | `100000` | Quota default |
| `TOKEN_QUOTA_RENEWAL_POLICY` | `ROLLING_24H` | `ROLLING_24H` \| `DAILY_RESET_UTC` |
| `QUOTA_RESERVATION_ESTIMATED_OUTPUT_TOKENS` | `2048` | Conservative estimate used only to reserve quota during an in-flight model call |
| `MODEL_MAX_CONCURRENT_REQUESTS_PER_MODEL` | `4` | Concurrency cap per model at `ModelRouter` |
| `QWEN_CODER_ENABLED` / `QWEN_NLP_ENABLED` | `false` | See §10 — the app starts and runs fully with both disabled |
| `QWEN_CODER_*` / `QWEN_NLP_*` (endpoint URL, model path, context length, timeouts, etc.) | see `backend/.env.example` | See §10 |

### Frontend

`frontend/.env.example` has one variable, baked into the build (not
read at runtime — see §13):

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `/api/v1` | Base path the SPA calls. A relative path is correct when Nginx routes `/api/` to the backend on the same origin (the deployment this README describes) — only change it if the frontend is served from a different origin than the API. |

---

## 7. PostgreSQL Installation

```bash
sudo systemctl enable postgresql
sudo systemctl start postgresql
sudo systemctl status postgresql   # verify: active (running)
```

Create the database and user matching your `DATABASE_URL` from §6.
The example below matches the *shape* the application expects
(`app_user` / `app_db`, as used throughout `.env.example` and
`docker-compose.yml`) — use your own generated password, not the
`app_password` dev default:

```bash
sudo -u postgres psql <<'SQL'
CREATE USER app_user WITH PASSWORD '<secure-password>';
CREATE DATABASE app_db OWNER app_user;
GRANT ALL PRIVILEGES ON DATABASE app_db TO app_user;
SQL
```

By default PostgreSQL only listens on `localhost` and authenticates
local connections via `peer`/`md5` — sufficient for the backend
running on the same host. If the backend is on a different host,
edit `postgresql.conf` (`listen_addresses`) and `pg_hba.conf`
(add an entry for the backend's address, `md5`/`scram-sha-256` auth —
**do not open Postgres to `0.0.0.0` or the public internet**, see
§25).

Verify connectivity with the exact URL the app will use:

```bash
psql "postgresql://app_user:<secure-password>@localhost:5432/app_db" -c '\conninfo'
```

---

## 8. Database Migration

The schema is managed entirely by Alembic
(`backend/alembic/`, config in `backend/alembic.ini`) —
`alembic/env.py` reads the connection string from application
settings (`DATABASE_URL`), so migrations always target whichever
database is configured in `backend/.env`.

```bash
cd /opt/ai-platform/app/backend
source /opt/ai-platform/venv/bin/activate

alembic upgrade head          # apply all migrations
```

Verify:

```bash
alembic current                # shows the applied revision
```

The last migration (`bdeda3f7a191_seed_initial_qwen_models.py`) seeds
the two Phase 5 model rows (`qwen2.5-coder-7b`, `qwen2.5-nlp-instruct-7b`)
that the chat API expects to be able to reference — do not skip it.

Rollback (only if the specific revision's `downgrade()` has actually
been written safely for a database already holding data — verify
before running against production, per `DEPLOYMENT.md`):

```bash
alembic downgrade -1           # one revision back
alembic upgrade head --sql     # preview pending migrations without applying
```

Do not create tables manually — every schema object is managed
through these migrations.

---

## 9. Redis (Optional — Multi-Worker Rate Limiting)

The application's `RateLimitMiddleware` keeps its per-client counters
in the memory of whichever process handled the request. **This
matters even on a single machine**: Gunicorn's worker model
(`backend/gunicorn.conf.py`) runs `WEB_CONCURRENCY` separate OS
processes, each with its own independent counter — so with the
default `WEB_CONCURRENCY` (up to 4), a client's real rate-limit budget
is up to 4× `RATE_LIMIT_REQUESTS_PER_MINUTE`, not the configured
value, exactly the way it would be across multiple Docker replicas
(`docker-compose.prod.yml` runs Redis for this exact reason — see
`PERFORMANCE.md`, "Rate limiter and performance metrics are
process-local").

If `WEB_CONCURRENCY=1` (a single Gunicorn worker), skip this section —
the in-memory limiter is already correct with only one process.

Otherwise, install Redis and point the backend at it:

```bash
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
redis-cli ping   # expect PONG
```

In `backend/.env`:

```text
RATE_LIMIT_REDIS_URL=redis://localhost:6379/0
```

Redis should be bound to `localhost` only (Ubuntu's default
`redis-server` config already does this) — never expose 6379 publicly.

---

## 10. Model Deployment (Qwen)

Both models run **locally** on this machine, as their own vLLM
OpenAI-compatible server processes using pre-downloaded weights — no
Ollama, no third-party model API. Full setup (dependency isolation,
config mapping, systemd units, GPU memory sizing) is in
[`docs/model-serving.md`](./docs/model-serving.md); summary:

```text
Backend (QwenProvider, an HTTP client — unchanged either way)
        ↓  OpenAI-compatible chat-completions API, over HTTP
vLLM server process (1 per model, this host, not per Gunicorn worker)
        ↓  loads weights once
Pre-downloaded local weights (QWEN_*_MODEL_PATH — already on disk;
                                nothing here downloads them)
```

- **Runtime:** vLLM, one dedicated process per model — not one per
  Gunicorn backend worker (a 7B model is ~14GB in bf16; loading it
  inside each of `WEB_CONCURRENCY` worker processes would multiply
  that by worker count). `backend/scripts/run_local_model_server.sh`
  starts it, reading the same `QWEN_*` variables in §6/`.env.example`.
- **Install:** vLLM lives in its **own** virtualenv, separate from
  `backend/venv` — never added to `backend/requirements.txt` (it pulls
  in a multi-GB, CUDA-specific PyTorch build the API server itself
  doesn't need). See `docs/model-serving.md`, "Dependency isolation."
- **Model files / weights:** `QWEN_*_MODEL_PATH` is both the `model`
  field `QwenProvider` sends and the actual weights location
  `run_local_model_server.sh` passes to `vllm serve` — one variable,
  not two. Weights must already be downloaded there; nothing in this
  repository downloads them.
- **GPU / CUDA:** required, on this host now (not an external
  system's concern). `QWEN_*_DEVICE`/`QWEN_*_DTYPE`/
  `QWEN_*_GPU_MEMORY_FRACTION` are load-bearing — translated directly
  into `vllm serve` flags. See `docs/model-serving.md`, "GPU memory,"
  for budgeting both models on one GPU.
- **Port / configuration:** unchanged from before — each model
  independently enabled via `QWEN_{CODER,NLP}_ENABLED` (default
  **disabled**); the application starts and the rest of the chat
  platform works fully without either.
- **Health check:** unchanged — `QwenProvider`'s existing error
  handling (connection failure, timeout, malformed response) covers
  "server unreachable" the same way regardless of what runs on the
  other end; see §20 Troubleshooting → "Model unavailable."
- **systemd:** `ai-platform-model-coder.service` /
  `ai-platform-model-nlp.service` — unit files in
  `docs/model-serving.md`, started before the backend (§17).

If you don't yet have weights downloaded or a GPU provisioned, leave
both `QWEN_*_ENABLED=false` — every other part of this deployment
guide still applies and the application is fully usable, just without
real model output.

---

## 11. Backend Startup

Entry point: `src.main:app` (`backend/src/main.py`), served in
production by Gunicorn with Uvicorn workers, per
`backend/gunicorn.conf.py` (`gunicorn -c gunicorn.conf.py src.main:app`).
**Do not use `uvicorn --reload` in production** — that's the
development-only invocation `docker-compose.yml` uses.

```bash
cd /opt/ai-platform/app/backend
source /opt/ai-platform/venv/bin/activate

# One-time / manual verification before wiring up systemd (§16):
GUNICORN_BIND=127.0.0.1:8000 \
WEB_CONCURRENCY=4 \
gunicorn -c gunicorn.conf.py src.main:app
```

- **Host/bind:** `GUNICORN_BIND` (default `0.0.0.0:8000` in
  `gunicorn.conf.py`). Bind to `127.0.0.1:8000` in any deployment where
  Nginx is the intended sole entry point (staging/production) — this
  is also the precondition for `TRUST_PROXY_HEADERS=true` in §6 to be
  safe.
- **Workers:** `WEB_CONCURRENCY` (default `min(4, cpu_count)`). Each
  worker is a separate OS process with its own DB connection pool —
  `WEB_CONCURRENCY × (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)` must
  stay under Postgres's `max_connections`. See §9 for why
  `WEB_CONCURRENCY > 1` needs Redis for correct rate limiting.
- **Environment:** development vs. production is controlled entirely
  by `backend/.env` (`ENVIRONMENT`, `DEBUG` — see §6), not by a
  different startup command.
- **Development mode**, for comparison (not for production use):
  ```bash
  cd /opt/ai-platform/app/backend
  source /opt/ai-platform/venv/bin/activate
  PYTHONPATH=. uvicorn src.main:app --reload
  ```

For persistent, boot-surviving startup, see §16 (systemd) — do not
rely on an administrator manually re-running this command after every
reboot.

---

## 12. Background Workers

```text
No background worker is required for the current implementation.
```

Confirmed by `backend/src/workers/` (present, empty — reserved for a
later phase) and `DEPLOYMENT.md`'s explicit statement that everything,
including model calls, runs synchronously within the request's async
event loop. There is no Celery/RQ/APScheduler/queue-consumer process
to install, configure, or add a systemd unit for.

---

## 13. Frontend Deployment

Framework: React + TypeScript + Vite (confirmed in
`frontend/package.json`; **not** Next.js — there is no server-rendering
step). The build produces a static SPA bundle; there is no Node.js
process running in production, only build-time tooling.

```bash
cd /opt/ai-platform/app/frontend
sudo -u aiplatform cp .env.example .env
# Edit .env if VITE_API_BASE_URL needs to differ from the default
# "/api/v1" — see §6 for when that applies.

sudo -u aiplatform npm ci
sudo -u aiplatform npm run build   # runs `tsc && vite build` — type-checks, then builds
```

This produces `frontend/dist/`. `VITE_*` variables are baked into the
bundle **at build time**, not read at container/process start — rerun
`npm run build` (not just restart a service) after changing
`VITE_API_BASE_URL`.

Nginx's shipped config (`nginx/nginx.conf.template`) serves the built
frontend directly from a hardcoded path:

```bash
sudo mkdir -p /var/www/frontend/dist
sudo cp -r /opt/ai-platform/app/frontend/dist/* /var/www/frontend/dist/
sudo chown -R www-data:www-data /var/www/frontend/dist
```

Re-run this copy step every time you rebuild the frontend (§22,
Upgrade Procedure).

---

## 14. Nginx Installation & Configuration

```bash
sudo systemctl enable nginx
sudo systemctl start nginx
```

`nginx/nginx.conf.template` is a complete `http { ... }` config block
(not a `sites-available` snippet) that assumes it is deployed as
`/etc/nginx/nginx.conf` itself — adjust the `include mime.types;` path
if your Nginx install layout differs. It has four placeholders to
substitute at deploy time:

| Placeholder | Bare-metal value |
|---|---|
| `__SERVER_NAME__` | `<YOUR_DOMAIN>` |
| `__API_UPSTREAM__` | `127.0.0.1:8000` (the comment in the template itself confirms this is the correct bare-metal value — `backend:8000` is the Docker-only value) |
| `__SSL_CERT_PATH__` | see §15 |
| `__SSL_KEY_PATH__` | see §15 |

```bash
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak   # back up the distro default
sudo cp /opt/ai-platform/app/nginx/nginx.conf.template /tmp/nginx.conf.rendered

sudo sed -i \
  -e "s#__SERVER_NAME__#<YOUR_DOMAIN>#g" \
  -e "s#__API_UPSTREAM__#127.0.0.1:8000#g" \
  /tmp/nginx.conf.rendered
# __SSL_CERT_PATH__ / __SSL_KEY_PATH__ are only referenced inside the
# commented-out HTTPS server block — substitute them in §15, after you
# have real certificate paths, then uncomment that block.

sudo cp /tmp/nginx.conf.rendered /etc/nginx/nginx.conf
sudo nginx -t        # syntax check before reloading
sudo systemctl reload nginx
```

What this configuration already provides, as shipped (verify against
`nginx/nginx.conf.template` directly if you customize it):

- `location /api/` → reverse-proxies to the backend, with
  `proxy_buffering off` (required for the chat API's Server-Sent-Events
  streaming to reach clients incrementally rather than being buffered)
  and generous timeouts (`proxy_read_timeout 300s`, must stay ≥ the
  configured `QWEN_*_REQUEST_TIMEOUT_SECONDS` plus headroom).
- `location /api/v1/auth/` → the same proxy, with a tighter
  `limit_req` zone (5r/min) specifically on auth endpoints — nginx's
  coarse first line of defense; the application's own per-account
  login lockout (`backend/src/services/auth_service.py`) is what
  actually survives an Nginx restart.
- WebSocket upgrade headers are wired (`map $http_upgrade
  $connection_upgrade`) for forward compatibility — nothing in the
  application currently uses WebSockets (chat streaming is SSE).
- `location = /healthz` → proxies to the backend's `/api/v1/health`
  for load balancers that expect that conventional path.
- `location /` → serves `frontend/dist` (§13), with long-cache headers
  on hashed build assets and no caching on `index.html`.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`) and `client_max_body_size 10m`.

---

## 15. HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
```

Requires a DNS `A`/`AAAA` record for `<YOUR_DOMAIN>` already pointing
at this host before requesting a certificate.

```bash
sudo certbot --nginx -d <YOUR_DOMAIN>
```

`certbot --nginx` edits the active Nginx config directly, which
conflicts with this repository's approach of rendering
`nginx.conf.template` as a whole file. Two supported approaches:

- **Simplest:** let `certbot --nginx` manage the HTTPS server block
  itself (it will add its own), and keep using the HTTP `server {}`
  block from the template for the reverse-proxy/static-file logic.
- **Matches the template exactly:** use `certbot certonly --nginx -d
  <YOUR_DOMAIN>` (obtains a certificate without editing your config),
  then manually set `__SSL_CERT_PATH__` /`__SSL_KEY_PATH__` in
  `/etc/nginx/nginx.conf` to the paths Certbot reports (typically
  `/etc/letsencrypt/live/<YOUR_DOMAIN>/fullchain.pem` /
  `.../privkey.pem`), uncomment the `server { listen 443 ssl http2;
  ... }` block already present (commented out) in
  `nginx/nginx.conf.template`, and also uncomment the `return 301
  https://$host$request_uri;` line in the HTTP block so port 80
  redirects to HTTPS. Then `sudo nginx -t && sudo systemctl reload
  nginx`.

Verify auto-renewal (Certbot installs a systemd timer/cron job by
default):

```bash
sudo certbot renew --dry-run
```

---

## 16. systemd Services

No systemd unit files exist in the repository (Docker's `CMD`/
`HEALTHCHECK` are the only process-supervision mechanism it ships
with) — the unit below is created for this manual deployment,
following the same command, user, and health-check the Docker image
uses.

`/etc/systemd/system/ai-platform-backend.service`:

```ini
[Unit]
Description=AI Platform backend (Gunicorn)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=aiplatform
Group=aiplatform
WorkingDirectory=/opt/ai-platform/app/backend
EnvironmentFile=/opt/ai-platform/app/backend/.env
Environment=GUNICORN_BIND=127.0.0.1:8000
ExecStart=/opt/ai-platform/venv/bin/gunicorn -c gunicorn.conf.py src.main:app
Restart=on-failure
RestartSec=5
# Give in-flight requests (including long SSE streams) time to finish
# on stop — matches gunicorn.conf.py's own graceful_timeout (30s).
TimeoutStopSec=35

# Least-privilege hardening (not required by the application, but has
# no functional cost here — the app writes nothing outside its own
# process and the database):
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/ai-platform/app/backend

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-platform-backend
sudo systemctl start ai-platform-backend
sudo systemctl status ai-platform-backend
```

Common operations:

```bash
sudo systemctl restart ai-platform-backend
sudo systemctl stop ai-platform-backend
journalctl -u ai-platform-backend -f      # follow logs — see §19
```

No `ai-platform-worker.service` — see §12.
`ai-platform-model-coder.service` / `ai-platform-model-nlp.service`
run the local vLLM servers (§10) — unit files in
`docs/model-serving.md`, not repeated here.

Nginx and PostgreSQL use their own distro-provided systemd units
(`nginx.service`, `postgresql.service`) — already enabled in §7/§14,
no custom unit needed.

---

## 17. Startup Order

```text
1. PostgreSQL           (systemctl start postgresql)
      ↓
2. Redis (if used)      (systemctl start redis-server — §9)
      ↓
3. Qwen model server(s) (systemctl start ai-platform-model-coder
                         ai-platform-model-nlp — §10; skip if
                         QWEN_*_ENABLED=false)
      ↓
4. Database migration   (alembic upgrade head — one-time/per-deploy, §8)
      ↓
5. Backend               (systemctl start ai-platform-backend)
      ↓
6. Frontend build        (npm run build + copy to /var/www — a build
                          step, not a running process; must exist
                          before Nginx serves it, but has no ongoing
                          startup dependency)
      ↓
7. Nginx                 (systemctl start nginx)
```

The order matters because: the backend's DB connection pool
(§11) needs a reachable, migrated database at startup, not just
eventually; Nginx's `upstream python_api` needs something listening
on `127.0.0.1:8000` before it can proxy successfully (a request
arriving before step 5 gets a 502, not a hang); and the frontend's
static files must exist on disk before Nginx's `location /` can serve
them. Once all services are running, restart order for routine
operations no longer matters this strictly — see §22 for the specific
sequencing an upgrade needs.

---

## 18. Health Checks

```bash
systemctl status postgresql
systemctl status redis-server        # only if §9 applies
systemctl status ai-platform-backend
systemctl status nginx
```

Application-level:

```bash
# Backend liveness — public, no auth required:
curl -f http://127.0.0.1:8000/api/v1/health
# Expect: {"status":"ok","environment":"production","version":"0.1.0"}

# Through Nginx (both are equivalent — /healthz is the
# load-balancer-conventional path the template also proxies):
curl -f https://<YOUR_DOMAIN>/healthz
curl -f https://<YOUR_DOMAIN>/api/v1/health
```

`GET /api/v1/system/diagnostics` is a second, deeper health endpoint
(actually checks DB reachability) but requires a Developer/Owner-role
JWT — not suitable for an anonymous load-balancer probe without a
service-level bypass; use `/api/v1/health` plus your own independent
DB check for that purpose, as `DEPLOYMENT.md` recommends.

Final verification sequence — only the checks that actually apply to
this application (confirmed against `docs/api/`, `docs/troubleshooting/README.md`,
and the ADRs; nothing here is invented):

```text
PostgreSQL         ✓  systemctl status postgresql
Redis (if used)    ✓  redis-cli ping
Backend            ✓  curl -f http://127.0.0.1:8000/api/v1/health
Nginx              ✓  curl -f https://<YOUR_DOMAIN>/healthz
Frontend           ✓  https://<YOUR_DOMAIN>/ loads the SPA shell
Registration        ✓  POST /api/v1/auth/register creates a pending user
User approval       ✓  a Manager can approve the pending user (see docs/manager-guide/)
Login               ✓  POST /api/v1/auth/login returns a token for an approved user
Model selection     ✓  GET /api/v1/admin/models lists the seeded Qwen rows (only meaningful once §10 is configured)
Chat                ✓  POST /api/v1/chats, then POST .../messages
Streaming           ✓  the same message request with "stream": true returns an SSE response
Token quota         ✓  GET /api/v1/users/me/quota returns current usage/limit
```

---

## 19. Logging

**Backend** — structured JSON lines (per-request: `request_id`,
`user_id`, `endpoint`, `duration_ms`, `status`, `error_type`; request
and response *bodies* are deliberately never logged — see
`SECURITY.md`) to stdout/stderr, captured by systemd/journald under
this deployment (Gunicorn's own `accesslog` is disabled to avoid
double-logging — see `backend/gunicorn.conf.py`):

```bash
journalctl -u ai-platform-backend -f          # follow
journalctl -u ai-platform-backend --since today
journalctl -u ai-platform-backend -p err      # errors only
```

journald's own retention/rotation policy (`/etc/systemd/journald.conf`
— `SystemMaxUse`, etc.) applies; the application does not implement
its own log rotation.

**Nginx** — standard distro locations:

```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

Rotated by the distro's default `logrotate` config
(`/etc/logrotate.d/nginx`) — no application-specific change needed.

**PostgreSQL:**

```bash
sudo journalctl -u postgresql -f
# or, depending on the distro's PostgreSQL packaging:
sudo tail -f /var/log/postgresql/postgresql-*-main.log
```

**Qwen model server(s)** — `journalctl -u ai-platform-model-coder -f`
/ `ai-platform-model-nlp` (same journald mechanism as the backend,
§10).

---

## 20. Troubleshooting

### Backend does not start

Check, in order: `python3.11 --version` (must be 3.11+) → the
virtualenv is activated and `pip install -r requirements.txt`
completed without error → `backend/.env` exists and `SECRET_KEY`/
`DATABASE_URL` are set → PostgreSQL is reachable with those exact
credentials (`psql "$DATABASE_URL_without_+asyncpg"`) → port 8000
isn't already in use (`sudo ss -lntp | grep 8000`). Full detail:
`journalctl -u ai-platform-backend -n 100`.

### Database connection failure

Check `systemctl status postgresql` is active → the user/password/
database name in `DATABASE_URL` match what §7 actually created →
`pg_hba.conf` permits the connecting host/user combination → for a
remote Postgres, `listen_addresses` includes the backend's interface,
not just `localhost`.

### Model unavailable

Check the model is actually enabled (`QWEN_*_ENABLED=true`) → the
configured `QWEN_*_ENDPOINT_URL` is reachable from the backend host
(`curl` it directly) → the external inference server's own process/
GPU/CUDA state (out of scope for this repository — consult that
runtime's own docs) → `QWEN_*_REQUEST_TIMEOUT_SECONDS` isn't shorter
than the model's actual generation time for long prompts.

### Frontend cannot reach backend

Check Nginx is running and its config passed `nginx -t` → `location
/api/` in `/etc/nginx/nginx.conf` points at the correct
`__API_UPSTREAM__` (`127.0.0.1:8000` for this deployment) → the
backend's own health check (§18) succeeds directly, bypassing Nginx →
`VITE_API_BASE_URL` matches how the frontend is actually served (§6) →
`CORS_ALLOW_ORIGINS` includes the frontend's real origin if the two
are ever served from different origins.

### Streaming does not work

Check `proxy_buffering off` is present on Nginx's `location /api/`
block (it is, as shipped — verify a custom edit didn't remove it) →
`proxy_read_timeout`/`proxy_send_timeout` (300s as shipped) are ≥
`QWEN_*_REQUEST_TIMEOUT_SECONDS` plus headroom → the request actually
included `"stream": true"` in the chat message payload.

### Permission errors

```bash
ls -la /opt/ai-platform/app
sudo systemctl show ai-platform-backend -p User -p Group
```

Confirm the `aiplatform` user owns everything under
`/opt/ai-platform/app` and `/opt/ai-platform/venv` (§3), and that
`/var/www/frontend/dist` is owned by `www-data` (§13, since Nginx
reads it as its own worker user).

### Port conflicts

```bash
sudo ss -lntp | grep -E ':(80|443|8000|5432|6379)\b'
```

Identify and stop whatever else is bound to a required port before
starting the corresponding service.

---

## 21. Deployment Validation Checklist

```text
[ ] OS prerequisites installed (§2)
[ ] Python 3.11 + venv created (§5)
[ ] Backend dependencies installed (§5)
[ ] backend/.env configured, SECRET_KEY generated (§6)
[ ] PostgreSQL installed, running, enabled at boot (§7)
[ ] Database + user created (§7)
[ ] Migrations applied — alembic upgrade head (§8)
[ ] Redis installed and configured, IF WEB_CONCURRENCY > 1 (§9)
[ ] Qwen endpoint(s) configured, IF a real inference server exists (§10)
[ ] Backend running under systemd, enabled at boot (§11, §16)
[ ] Frontend built (npm run build) and copied to /var/www/frontend/dist (§13)
[ ] Nginx installed, configured, enabled at boot (§14)
[ ] HTTPS configured and auto-renewal verified (§15)
[ ] Startup order followed end-to-end from a clean boot (§17)
[ ] Health checks passing: backend, Nginx, (Redis if used) (§18)
[ ] Registration + user approval working (§18)
[ ] Login working (§18)
[ ] Chat creation and messaging working (§18)
[ ] Model selection working, IF Qwen is configured (§18)
[ ] Streaming (SSE) working (§18)
[ ] Token quota endpoint working (§18)
[ ] Logs accessible via journalctl / Nginx log files (§19)
[ ] Backup job scheduled (§24)
[ ] Security checklist reviewed (§25)
```

---

## 22. Upgrade Procedure

```text
1. Back up the database (§24) — always, before any migration.
2. Announce/expect brief API unavailability if WEB_CONCURRENCY-based
   rolling restart isn't set up; this deployment method (a single
   systemd unit) restarts all workers together, unlike Docker's
   `--no-deps backend` per-replica rolling update.
3. git fetch / git checkout <new-tag-or-branch> (§4).
4. source venv/bin/activate && pip install -r requirements.txt
   (picks up any dependency changes).
5. alembic upgrade head (§8) — run BEFORE restarting the backend, so
   it never serves against a schema mid-migration.
6. npm ci && npm run build in frontend/, then re-copy dist/ to
   /var/www/frontend/dist (§13).
7. sudo systemctl restart ai-platform-backend
8. sudo systemctl reload nginx   (only needed if nginx.conf itself
   changed — a frontend rebuild alone doesn't require this, since
   Nginx reads the files from disk on each request)
9. Run the health checks in §18.
```

Restart the model services only if the update changed `QWEN_*` env
vars or `run_local_model_server.sh` itself:
`sudo systemctl restart ai-platform-model-coder ai-platform-model-nlp`
(§10). A backend-only code change does not require this.

---

## 23. Rollback Procedure

```text
Application code:      git checkout <previous-tag> ; pip install -r
                        requirements.txt ; systemctl restart
                        ai-platform-backend
Python dependencies:   covered by the same `pip install -r
                        requirements.txt` against the checked-out
                        commit's requirements.txt
Database migrations:   `alembic downgrade -1` — ONLY if the specific
                        revision's downgrade() has been verified safe
                        for a database already holding production
                        data (not guaranteed for every migration in
                        alembic/versions/ — check the file itself
                        first). When in doubt, restore the pre-upgrade
                        backup (§24) into a fresh database instead of
                        trusting an untested downgrade path.
Frontend:               rebuild from the previous tag's frontend/ and
                        re-copy to /var/www/frontend/dist (§13, §22)
Model configuration:   revert backend/.env's QWEN_* values if the
                        upgrade changed them; no code-level rollback
                        needed since the model server itself is
                        external (§10)
```

Always take a fresh database backup (§24) immediately before
attempting any rollback that touches migrations.

---

## 24. Backup & Recovery

What to actually back up:

```text
Database                    — yes, the only source of persistent
                               application data
backend/.env                — yes, configuration (store securely,
                               separately from routine DB backups —
                               it contains secrets)
Model configuration          — only the env vars above; no separate
                               model config file exists in this repo
Generated/cache data         — no — nothing in this application
                               generates persistent cache data outside
                               the database
```

```bash
# Backup
pg_dump -Fc --dbname="$DATABASE_URL" \
  -f /opt/ai-platform/backups/backup_$(date +%Y%m%d_%H%M%S).dump

# Restore (into a fresh/isolated database first — verify before
# pointing production traffic at a restored database):
pg_restore --clean --if-exists --dbname="$DATABASE_URL" \
  /opt/ai-platform/backups/backup_20260101_000000.dump
```

Schedule the backup command via cron or a systemd timer on the
`aiplatform` user; retention policy is `<VALUE_TO_CONFIGURE>` per your
organization's requirements — not specified by the repository.

---

## 25. Security Checklist

```text
[ ] No secrets committed — backend/.env and any .env* file with real values are excluded from version control (no .gitignore ships with this repository as of this writing; add one covering .env, .env.*, !*.env.example before your first commit of local config)
[ ] Strong, unique DATABASE_URL password (not the "app_password" dev default)
[ ] Strong, unique SECRET_KEY, different per environment
[ ] Application runs as a non-root system user (aiplatform — §3, §16)
[ ] Firewall configured (ufw/iptables) — only 80/443 open publicly
[ ] Backend (8000) bound to 127.0.0.1, not 0.0.0.0, and/or firewalled off (§11)
[ ] TRUST_PROXY_HEADERS=true ONLY if the above is true (§6, §11)
[ ] PostgreSQL not publicly exposed (§7)
[ ] Redis not publicly exposed, if used (§9)
[ ] Qwen model server ports (8001/8002 default) bound to localhost / firewalled, not publicly exposed (§10)
[ ] HTTPS enabled, certificate auto-renewal verified (§15)
[ ] Nginx security headers present (shipped by default — §14)
[ ] DEBUG=false in production (§6)
[ ] Structured (JSON) production logging enabled — LOG_JSON=true (§6, §19)
[ ] Database backups scheduled (§24)
[ ] File permissions correct — aiplatform owns app/venv, www-data owns the served frontend (§3, §13)
[ ] systemd service runs with least privilege (NoNewPrivileges, ProtectSystem — §16)
```

---

## 26. Docker vs. Manual Deployment

Docker (`docker-compose.yml` for development,
`docker-compose.prod.yml` for staging/production) remains this
repository's primary, actively-maintained deployment path — see
`DEPLOYMENT.md` for that procedure in full. This README describes an
equivalent manual deployment of the exact same application on a
Linux host, for environments where Docker isn't available or isn't
wanted. Both should result in the same running architecture (Nginx →
Backend → PostgreSQL, with Redis and Qwen as the same optional/
external dependencies either way) — nothing about the application's
behavior, API, or data model differs between the two. This README
does not replace, modify, or remove any Docker file in this
repository.
