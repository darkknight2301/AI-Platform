# Backend "API process" image — see ../DEPLOYMENT.md.
#
# Does NOT bundle Postgres or the Qwen model server; those are
# separate services this container reaches over the network
# (DATABASE_URL, QWEN_*_BASE_URL). See docker-compose.yml.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build deps only where needed (asyncpg/bcrypt wheels are prebuilt for
# slim on common platforms, but keep gcc available in case a
# dependency needs to compile from source on the target arch).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini gunicorn.conf.py ./

# Non-root: the app never needs root inside the container.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Container-level health check mirrors the orchestrator-level one
# (nginx's /healthz, or a k8s readinessProbe hitting the same path) —
# see DEPLOYMENT.md "Health checks".
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Migrations run as a separate step before the app starts (see
# docker-compose.yml's `migrate` service and DEPLOYMENT.md's
# "Migration process") — this image's default command only serves
# traffic, so a rolling deploy never accidentally races two containers
# both trying to migrate at once.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "src.main:app"]
