"""Gunicorn config for the production ASGI "API process" (see
DEPLOYMENT.md, "API process / worker process / model process").

This is the single process group that serves `src.main:app` — it is
NOT the same thing as a background task worker (this codebase has no
such process; see DEPLOYMENT.md) and it is NOT the model inference
process (Qwen runs as its own separate service, reached over HTTP —
see `src/model_layer/providers/qwen/`). Each gunicorn *worker* here is
one OS process running the full FastAPI app with its own event loop
and its own DB connection pool — see DEPLOYMENT.md's pool-sizing math
before changing `workers`.

Usage:
    gunicorn -c gunicorn.conf.py src.main:app
"""
from __future__ import annotations

import multiprocessing
import os

# --- Workers -----------------------------------------------------------
# One event loop per worker handles many concurrent requests already
# (this app is async I/O-bound: DB queries and Qwen HTTP calls), so
# "2 x CPU + 1" (the generic gunicorn default) is usually more workers
# than needed and just multiplies the DB connection pool — see
# PERFORMANCE.md bottleneck #2. Override via WEB_CONCURRENCY for a
# specific deployment; default here is deliberately conservative.
workers = int(os.environ.get("WEB_CONCURRENCY", min(4, multiprocessing.cpu_count())))
worker_class = "uvicorn_worker.UvicornWorker"

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# --- Graceful shutdown ---------------------------------------------------
# Give in-flight requests (including long-lived SSE streams) time to
# finish instead of being killed mid-response when a deploy rolls the
# process. Orchestrators (docker/k8s) should send SIGTERM and then wait
# at least this long before SIGKILL.
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
# A request that hasn't produced any activity in this long is
# considered stuck and its worker is recycled — set well above the
# longest expected model-generation time (see QWEN_*_TIMEOUT_SECONDS)
# so a slow-but-healthy model response is never killed.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
keepalive = 5

# --- Health / lifecycle --------------------------------------------------
# Liveness/readiness are HTTP endpoints (GET /api/v1/health,
# /api/v1/system/diagnostics), not a gunicorn setting — see
# DEPLOYMENT.md. `preload_app=False` (default) is intentional: each
# worker builds its own DB engine / ModelRouter via the app's lifespan
# hook (src/main.py), which would be shared incorrectly across forked
# workers if preloaded.
preload_app = False
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "0"))  # 0 = disabled; set >0 to recycle workers periodically in production
max_requests_jitter = 50

# --- Logging ---------------------------------------------------------
# Access/error logs go to stdout/stderr (container-native); structured
# request logging is handled by the app itself
# (src/core/middleware.py:RequestLoggingMiddleware), so gunicorn's own
# access log is kept minimal to avoid double-logging every request.
accesslog = None
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
