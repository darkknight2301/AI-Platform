# Authentication / Authorization Layer

This package is reserved for authentication (identity/session/token
handling) and authorization (permission/role checks) logic.

**Status:** structural placeholder only. Phase 1 establishes the
project layout; no authentication or authorization business logic is
implemented yet (see project ARCHITECTURE.md and scope control in the
Phase 1 instructions). It will be implemented in a later phase.

Planned separation:

- `authentication.py` — identity verification, token issuance/validation.
- `authorization.py` — role/permission/group-based access checks.
- `dependencies.py` — FastAPI dependencies (`get_current_user`, etc.)
  used by routers to enforce server-side authorization.

All authorization decisions will be enforced in the Python backend —
never trusted from the frontend.
