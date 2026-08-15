# 0006 — Registration group-assignment policy

## Status
Accepted

## Context
Phase 3 requires "a clear group assignment policy" for registration
and explicitly: "Do not allow users to arbitrarily assign themselves
privileged groups." The data model (Phase 2) has two independent
privilege-adjacent fields on `User`: `group_id` (organizational
membership) and `role` (the `Role` enum — USER/MANAGER/DEVELOPER/OWNER,
see ADR 0005). Only `role` actually carries privilege; `Group` itself
has no inherent privilege level, only a name/status.

## Decision
1. **`role` is never client-settable, anywhere in the registration
   request.** `RegisterRequest` (see `src/schemas/auth.py`) has no
   `role` field at all — not merely a default that a determined client
   could override. Every self-registered account is created with
   `Role.USER` by `AuthService.register_user`, unconditionally. If a
   client sends an extra `"role": "OWNER"` field in the JSON body,
   Pydantic silently ignores unknown fields and it has no effect —
   verified by
   `test_registration_creates_pending_user_with_forced_role_user`.
2. **`group_id` is client-suppliable, but only to request membership in
   an existing, `ACTIVE` group** — chosen from public information (the
   list of groups), not created or invented by the registrant. This
   does not grant any privilege: it only determines which Manager's
   approval queue the pending account appears in.
3. **The account remains `PENDING` regardless of which group was
   requested.** No self-registered account is ever immediately
   `ACTIVE`; a Manager (of the requested group) or an Owner must
   explicitly approve it (see `UserService.approve_user`). This is the
   actual control point — even if group selection were somehow
   privilege-relevant, PENDING status blocks login until a human with
   authority reviews the account.
4. **Changing `role` or `group_id` after registration is Owner-only**
   (`PATCH /api/v1/admin/users/{id}`, see `src/api/v1/routers/admin.py`
   and `UserAdminUpdate`). Managers can change a pending user's
   *status* (approve/reject) within their own group, but cannot change
   `role` or move a user to a different group.

## Consequences
- There is no code path — not a hidden field, not a race condition — by
  which a registrant can end up with anything other than
  `Role.USER` / `UserStatus.PENDING` immediately after registration.
- Group selection at registration is a convenience (routes the pending
  account to the right Manager) with no security weight of its own;
  the security-relevant gate is entirely in the approval step and in
  role assignment being Owner-only.
- If a future requirement introduces group-level privilege (e.g. an
  "admin group" that grants elevated access merely by membership),
  this ADR's reasoning would need to be revisited — currently no such
  coupling exists in the data model.
