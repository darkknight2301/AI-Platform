# Troubleshooting

## Login fails with "pending manager approval"

Expected, not a bug — your account was created but hasn't been
approved yet. A Manager in your group needs to approve it (Manager
Guide, "User approval"). There is no self-service bypass.

## Login returns 429 "Too many failed login attempts"

You (or someone) failed to log in 5+ times on this account in the last
15 minutes (`src/services/auth_service.py`, Phase 10 brute-force
protection). Wait 15 minutes from the last failure, or have an Owner
verify the account isn't otherwise compromised if this wasn't you.

## "Too many requests" / 429 on ordinary use

Two independent layers can produce this: nginx's `limit_req` (coarse,
per-IP, see `nginx/nginx.conf.template`) or the app's own
`RateLimitMiddleware` (`src/core/middleware.py`). If it's happening
under normal single-user usage, the configured limits
(`RATE_LIMIT_REQUESTS_PER_MINUTE`, nginx's `rate=20r/s`) are probably
too tight for the deployment's real traffic — see `PERFORMANCE.md`.

## Chat creation fails with a limit error

You've hit `max_active_chats` (default or your group/user override —
see Owner Guide, "Quotas"). Delete an old chat to free a slot, or ask
an Owner to raise your limit.

## Sending a message fails with a quota error

Your token quota is exhausted for the current window. Check `GET
/users/me/quota` (or the usage panel in the UI) for when it renews —
depends on `TOKEN_QUOTA_RENEWAL_POLICY` (rolling 24h vs. daily UTC
reset; ADR 0010).

## A model doesn't appear in the picker

Either it's disabled (Owner Guide, "Models") or its
`QWEN_*_ENABLED`/`QWEN_*_ENDPOINT_URL` isn't configured — `GET
/system/models` (Developer dashboard) shows live status per model,
including ones an Owner enabled in the database but that never
actually registered at startup because their env config was missing
(see `src/model_layer/bootstrap.py` — a misconfigured provider logs
`qwen_provider_not_registered` rather than crashing the app).

## Streaming responses hang or cut off mid-reply

Check, in order: (1) `QWEN_*_REQUEST_TIMEOUT_SECONDS` on the backend
vs. nginx's `proxy_read_timeout`/`proxy_send_timeout` — nginx must be
≥ the backend's timeout or it cuts the connection first (see
`DEPLOYMENT.md`, "Nginx"); (2) `proxy_buffering off` must be set on
`/api/` in the active nginx config — buffering re-enabled anywhere in
the chain (a CDN, a misconfigured proxy) will hold the whole response
until complete instead of streaming it; (3) `GET
/system/performance`/`GET /system/logs` for whether the model backend
itself is slow/erroring (a 502 on the send-message call means the
model backend failed, not the API).

## "Model backend failed" / 502 on sending a message

The API and database are fine; the configured Qwen endpoint didn't
respond successfully (`src/services/errors.py::ChatServiceError`, see
the API guide's error-shape section). Check the model server's own
health directly, and `QWEN_*_ENDPOINT_URL` is actually reachable from
the API container/host — this is infrastructure the application code
doesn't control (see `DEPLOYMENT.md`, "Model process").

## Database connection errors under load

Likely pool exhaustion — see `PERFORMANCE.md` bottleneck #2's
`workers × (pool_size + max_overflow) ≤ Postgres max_connections`
math. `SELECT count(*) FROM pg_stat_activity;` against the target
Postgres to confirm.

## A user can see another group's data

This should be structurally impossible (`can_manage_group`,
ownership-scoped repository queries — see `SECURITY.md`,
`test_admin_dashboards.py`). If this is observed, it's a security
incident, not a config issue — capture the exact request (method,
path, both users' roles/groups) and treat it as a P0, not something to
work around.

## Migrations fail on deploy

Run `alembic upgrade head --sql` first to see the pending SQL without
applying it — catches most issues (a manually-altered column, an
out-of-order migration) before they hit production. See
`DEPLOYMENT.md`, "Database" — migrations must run as their own step
before any API replica starts serving traffic, never from inside a
starting API container's own boot sequence.
