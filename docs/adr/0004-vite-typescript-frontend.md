# 0004 — Use a minimal Vite/TypeScript frontend for the foundation phase

## Status
Accepted (foundation only — subject to revisit)

## Context
No existing frontend exists in this repository. Common Instructions
allow "the minimum required HTML/CSS/JavaScript/TypeScript ecosystem
appropriate for the selected frontend framework," and Phase 1 scope
control prohibits adding unrequested functionality. No specific UI
framework (React, Vue, etc.) has been requested yet.

## Decision
Scaffold a minimal Vite + TypeScript project with no UI framework
beyond what Vite's `vanilla-ts` template provides. It talks to the
backend's `/api/v1/health` endpoint to confirm end-to-end wiring works,
and nothing more.

## Consequences
- Fast build/dev iteration, minimal dependency surface, no framework
  lock-in decided prematurely.
- If a later phase's UI requirements (e.g. complex interactive chat
  UI, component reuse needs) justify a framework such as React, that
  can be introduced without restructuring the backend or the
  Nginx/deployment story — only `frontend/` changes.
- This decision should be revisited once actual UI requirements for
  the chat/business functionality are known.
