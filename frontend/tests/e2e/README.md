# E2E tests (Playwright)

Real browser tests against the actual React app — no React Testing
Library, no framework substitution. Requires the full stack running
(backend + Postgres + frontend dev server).

## Setup (once per environment)

```bash
# 1. Backend + Postgres running (see backend/README.md / docker-compose)
# 2. Seed the one Owner account these tests need to approve/promote users:
cd backend
python -m perf.seed_e2e_owner

# 3. Install Playwright + browsers
cd ../frontend
npm install
npx playwright install --with-deps chromium
```

## Run

```bash
cd frontend
npm run test:e2e
```

`playwright.config.ts` starts the Vite dev server itself
(`reuseExistingServer` in local dev); it does **not** start the
backend or database — those must already be up at
`http://localhost:8000`.

## Notes

- Tests create their own users via the API (`tests/e2e/helpers.ts`) —
  no shared fixtures/seed data beyond `e2e_owner`, so tests can run in
  any order and don't collide on usernames (all suffixed with a
  timestamp + random number).
- `fullyParallel: false` in the config: dashboard tests read
  global-ish state (audit log, user lists) that other tests also
  write, so specs run sequentially to avoid flaky cross-test reads.
- The chat-limit test in `chat.spec.ts` assumes a low
  `DEFAULT_MAX_ACTIVE_CHATS` in the test environment; it self-skips
  (doesn't fail) if the configured limit is high enough that 25 chats
  don't reach it.
