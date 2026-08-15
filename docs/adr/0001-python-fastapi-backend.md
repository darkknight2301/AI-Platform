# 0001 — Use Python/FastAPI as the sole backend language and framework

## Status
Accepted

## Context
The application needs a single, consistent backend language across
API, business logic, authentication/authorization, database access,
model orchestration, background workers, and CLI/maintenance tooling,
per project policy. Introducing a second backend language would
fragment tooling, testing, and operational knowledge without a strong
technical justification.

## Decision
Use Python as the only backend language, with FastAPI as the web
framework. FastAPI was chosen over alternatives (Flask, Django) because
it is async-native (important for streaming model responses and
concurrent request handling), integrates directly with Pydantic for
request/response validation, and generates OpenAPI documentation with
no extra tooling.

## Consequences
- All backend code (API, services, repositories, workers, CLI tools)
  lives in one language and one dependency ecosystem.
- Async support is available throughout the stack without bridging
  between sync and async code paths.
- Any future need for a second backend language must be justified by a
  strong technical requirement, not convenience.
