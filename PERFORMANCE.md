# Performance

This document is Phase 11's performance analysis: what was tested,
what was found, and what was changed as a result. It complements
`ARCHITECTURE.md` (how the system is built) and `SECURITY.md` (what's
protected) rather than repeating either.

## API scalability vs. model inference scalability

These are deliberately separate concerns, load-tested and reasoned
about independently:

- **API scalability**: can the Python API + database handle 500+
  registered users doing normal chat-app things (list chats, read
  history, check quota, hit admin dashboards) concurrently? This is
  bounded by uvicorn worker count, the database connection pool, and
  ordinary web-tier CPU/memory — none of it touches model inference
  latency.
- **Model inference scalability**: can the configured model backend(s)
  (Qwen 2.5 Coder / NLP, or whatever `MODEL_*_BASE_URL` points at)
  keep up with concurrent generation requests? This is bounded by the
  inference server itself — GPU/CPU capacity, batch size, context
  length — none of which this codebase controls.

Conflating the two produces the wrong fix: throwing more uvicorn
workers at a slow *model* won't help, and a bigger/faster GPU won't
fix a starved database connection pool. `backend/perf/locustfile.py`
is deliberately meant to be run against `MockProvider` (near-zero,
constant latency) specifically so its numbers measure the API tier in
isolation — see the module docstring.

## Load test: how to actually run it

```bash
cd backend
pip install locust --break-system-packages
python -m perf.seed_users --count 500          # 500 ACTIVE users + 1 Owner
locust -f perf/locustfile.py --host http://localhost:8000
```

Recommended profile for the "500+ users" acceptance scenario: 500
simulated users, spawn rate 10/s, run for at least 5 minutes so the
rolling/24h token-quota and chat-limit code paths (which do extra
queries — see `services/quota_service.py`) are exercised under
sustained load, not just a cold burst.

While it runs, watch:
- Locust's own p50/p95/p99 per named endpoint.
- `GET /api/v1/system/performance` (Developer dashboard, Phase 9) —
  `average_response_time_ms` and `requests_by_status_class`, which are
  populated by `PerformanceMiddleware` (`src/core/middleware.py`).
- `SELECT count(*) FROM pg_stat_activity;` against the target Postgres
  instance, to see actual connection usage vs. the configured pool
  (see below).

This was not executed against a live environment as part of this
change (no network/DB access in this environment — see the caveats
this project has flagged in every phase requiring a running stack).
The analysis below is therefore architectural: real numbers from an
actual run should replace the estimates here.

## Bottlenecks identified

### 1. No bound on concurrent requests to a single model — fixed

Before this phase, `ChatService` called straight through to
`ModelProvider.generate`/`.stream` with no concurrency limit at all.
Every simultaneous chat request would reach the model backend
directly; the only limits in play were `httpx.AsyncClient`'s default
connection-pool ceiling (100 connections) and whatever the backend
itself did under overload (typically: get slow, then start timing
out or erroring for everyone).

**Fix**: `ModelRouter.acquire_slot()` (`src/model_layer/router.py`)
now gates every `generate`/`stream` call through a per-`model_key`
`asyncio.Semaphore`, sized by
`MODEL_MAX_CONCURRENT_REQUESTS_PER_MODEL` (default 4 — conservative
for a single small inference server; tune to the real backend's
measured concurrent capacity). Excess requests queue at this seam
instead of piling onto the backend. A request that has to wait logs a
`model_request_queued` structured entry with the wait time, so queue
pressure is visible without a separate metrics system. Covered by
`tests/unit/test_model_layer.py::test_acquire_slot_*`.

This is the direct, code-level answer to "model request queueing" —
previously there was none.

### 2. Database connection pool sizing vs. worker count — documented, not auto-fixed

`database_pool_size` (default 10) + `database_max_overflow` (default
20) = 30 connections **per engine instance**. Since `engine` in
`src/db/session.py` is a module-level singleton, that's 30 connections
per **uvicorn worker process** — a multi-worker deployment multiplies
this. At 500 concurrent users hitting endpoints that touch the DB
(nearly all of them), a single worker's 30-connection pool will queue
requests once >30 are mid-transaction simultaneously; with N workers
you need N × 30 ≤ Postgres's `max_connections` (default 100) or
you'll see connection-acquisition failures instead of pool queueing.

This wasn't changed in code because the right numbers depend on the
deployment's actual worker count and the target Postgres instance's
`max_connections`/`shared_buffers`, which aren't knowable from this
codebase alone. **Operational guidance**: for N uvicorn workers,
either keep `N × (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW) ≤
Postgres max_connections`, or front the database with PgBouncer in
transaction-pooling mode (standard practice for this exact multi-worker
fan-out, and out of scope for the application code itself).

### 3. Rate limiter and performance metrics are process-local — rate limiter fixed, metrics still process-local by design

`RateLimitMiddleware` and `PerformanceMiddleware` both originally kept
in-memory state per process, under-enforcing/under-reporting once
horizontally scaled. `RateLimitMiddleware` is now backed by a pluggable
`RateLimitStore`: in-memory by default (unchanged, correct for a single
instance) or `RedisRateLimitStore` when `RATE_LIMIT_REDIS_URL` is set,
which gives every replica a shared, correctly-enforced counter.
`docker-compose.prod.yml` runs a `redis` service and sets this by
default, since it defaults to `BACKEND_REPLICAS=2`.

`PerformanceMiddleware`/`PerformanceMetrics` remain process-local,
deliberately: they back a diagnostics endpoint, not a security or
correctness control, so a per-replica view (or querying each replica
individually) is an acceptable operational trade-off that doesn't
justify the same fix. Exporting them to a real metrics backend
(Prometheus, etc.) instead of Redis-aggregating an ad hoc in-memory
struct remains the right eventual fix if per-replica visibility stops
being sufficient — not implemented here, tracked as a future
improvement rather than a defect.

### 4. Streaming response duration vs. the request-logging/rate-limit middleware — checked, no issue found

`RequestLoggingMiddleware` and `RateLimitMiddleware` wrap the full
request including `StreamingResponse` bodies (since `call_next`
doesn't return until the streaming generator is exhausted in
`BaseHTTPMiddleware`'s implementation) — so a long-lived SSE stream
correctly counts as one in-flight request for rate-limiting purposes
and its full duration is logged, not just time-to-first-byte. No
change needed; confirmed by reading `starlette.middleware.base`'s
`call_next` semantics and by `test_send_message_streaming` /
`test_phase11_concurrency.py` passing with streaming endpoints in the
same client.

### 5. Frontend: chat history / message list re-renders

Not investigated in depth — the frontend is React (`frontend/src/`,
ADR 0004), and Phase 11's frontend testing requirement (Playwright, see
`frontend/tests/e2e/`) is functional, not a performance profiling
pass. `ChatView`/`MessageBubble` render via normal React reconciliation
keyed by message id (`frontend/src/components/ChatView.tsx`), which is
the standard-correct pattern; a long chat (hundreds of messages) would
be the first place to profile if this became a reported issue, but
there's no evidence of one yet.

## What was NOT changed

- No caching layer was added (e.g. for `/models`, `/admin/config`) —
  premature without real traffic numbers showing it's needed, and
  every one of these endpoints is already a single indexed-PK or
  small-table query.
- No change to `database_pool_size`/`database_max_overflow` defaults —
  see bottleneck #2; the correct value is deployment-specific, not a
  code constant.
- No load-balancer/horizontal-scaling changes — out of scope for the
  application code.
