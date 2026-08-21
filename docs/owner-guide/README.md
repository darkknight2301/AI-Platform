# Owner Guide

Owner dashboard: `/dashboard` with the Owner role — the only role with
system-wide (all-groups) visibility and configuration access.

## Users

**Users & roles** tab: every user, every group. Change role or status
inline (dropdowns), or reassign a user to a different group. Role
changes take effect immediately (existing sessions re-check role on
each request — no re-login needed for the change to apply, but a
demoted user's *currently open* dashboard tabs won't disappear until
their next navigation/request). Every change here is audited
(`ADMIN_UPDATE_USER`).

## Groups

**Groups** tab: create a group, or toggle a group's active/inactive
status. A group's quota overrides (`max_active_chats_override`,
`token_quota_override`) aren't exposed in this tab's UI today — set
them via `PATCH /admin/groups/{id}` directly (see the API guide) if
needed; the dashboard shows name/status only.

## Roles

There's no separate "Roles" screen — role assignment happens per-user
in the **Users & roles** tab. The four roles (`USER`, `MANAGER`,
`DEVELOPER`, `OWNER`) are fixed in code
(`backend/src/models/enums.py::Role`), not configurable data; adding a
fifth role is a code change, not an admin action.

## Models

**Models** tab: register a new model (key, display name, category,
provider, version) or toggle an existing one enabled/disabled.
Disabling a model doesn't delete history that used it — existing chats
keep working, but it drops out of the picker for new chats. See the
Developer Guide's "Adding a model" for what registering a genuinely
new backend (not just a new Qwen deployment) additionally requires in
code.

## Quotas

Set per-group or per-user overrides via `PATCH /admin/groups/{id}` /
`PATCH /admin/users/{id}` (`token_quota_override`,
`max_active_chats_override`) — see the API guide. Absent an override,
everyone uses the system defaults (`DEFAULT_TOKEN_QUOTA`,
`DEFAULT_MAX_ACTIVE_CHATS` — see **System configuration** below).
Renewal policy (`TOKEN_QUOTA_RENEWAL_POLICY`: rolling 24-hour window
vs. fixed daily UTC reset) is a global setting, not per-group — see
ADR 0010 for why.

## Audit

**Audit logs** tab: every recorded action system-wide — registration,
approval/rejection, login/logout (including failed logins and
lockouts), role/model/quota changes, chat deletion, prompt edits, and
every admin operation. This is the complete record; Managers only see
their own actions (`/users/me/activity`), Owners see everything.

## System configuration

**System configuration** tab: read-only snapshot of non-secret
settings (app name, environment, rate limit, token expiry, default
quota/chat-limit values, renewal policy). Deliberately never shows
`SECRET_KEY` or `DATABASE_URL` — those aren't part of the response
schema at all, not filtered out of a larger one (verified by
`test_config_endpoint_never_exposes_secret_key`,
`backend/tests/integration/test_phase10_security.py`). Changing these
values requires editing environment variables and restarting the
service — there's no live-config-edit endpoint, intentionally (see
`SECURITY.md`).
