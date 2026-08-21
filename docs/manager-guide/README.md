# Manager Guide

Manager dashboard: `/dashboard` after logging in with the Manager
role. Everything here is scoped to your own group — a Manager cannot
see or act on users, usage, or activity from any other group; this is
enforced server-side (`can_manage_group` / `user_service`), not just
hidden in the UI (see `SECURITY.md`).

## User approval

The **Pending users** tab lists registrations awaiting a decision.
**Approve** activates the account (it can now log in, as a plain
`USER`). **Reject** marks it `REJECTED` — the person will see that
status if they try to log in. Both actions are logged (see
"Authorized activity" below) and cannot be undone from the UI (an
Owner can change a user's status directly if a mistake needs
correcting).

## Group management

The **Group** tab shows your group's name, member count, and every
user in it (with their current status). You cannot rename your group,
change its quota overrides, or move users into/out of it — those are
Owner-only (`docs/owner-guide/README.md`). If your group needs those
changes, ask an Owner.

## Usage

The **Group** tab also shows aggregate token usage for your group —
total tokens, input/output split, and record count. This is read-only
reporting; it doesn't let you cap an individual user's usage (that's a
quota override, Owner-only).

## Authorized activity

Shows a log of approvals/rejections **you personally performed** — not
everything that happened in your group, just your own actions (see
`GET /users/me/activity` in the API guide). This is intentionally
self-scoped: it's a record of what you're accountable for, not a
general group audit trail (Owners have that at `/admin/audit-logs`).
