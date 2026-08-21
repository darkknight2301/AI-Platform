import { APIRequestContext, Page, expect } from "@playwright/test";

export const API_BASE = "http://localhost:8000/api/v1";
export const DEFAULT_PASSWORD = "correct-horse-1";

export function uniqueUsername(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
}

/** Registers a user via the API and immediately approves them using a
 * pre-existing Owner account, so UI tests that need an ACTIVE user
 * don't have to drive the registration+approval UI every single time
 * (that flow gets its own dedicated test in auth.spec.ts). Returns the
 * created username/password for UI login. */
export async function createActiveUser(
  request: APIRequestContext,
  opts: { role?: "USER" | "MANAGER" | "DEVELOPER" | "OWNER"; usernamePrefix?: string } = {},
): Promise<{ username: string; password: string; id: string }> {
  const username = uniqueUsername(opts.usernamePrefix ?? "e2e_user");
  const registerResp = await request.post(`${API_BASE}/auth/register`, {
    data: { username, email: `${username}@example.com`, password: DEFAULT_PASSWORD },
  });
  expect(registerResp.ok()).toBeTruthy();
  const user = await registerResp.json();

  const ownerToken = await ensureOwnerToken(request);
  const approveResp = await request.post(`${API_BASE}/users/${user.id}/approve`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
  });
  expect(approveResp.ok()).toBeTruthy();

  if (opts.role && opts.role !== "USER") {
    const roleResp = await request.patch(`${API_BASE}/admin/users/${user.id}`, {
      headers: { Authorization: `Bearer ${ownerToken}` },
      data: { role: opts.role },
    });
    expect(roleResp.ok()).toBeTruthy();
  }

  return { username, password: DEFAULT_PASSWORD, id: user.id };
}

let cachedOwnerToken: string | null = null;

/** The test suite needs at least one Owner to approve/promote other
 * users through the API. Since self-registration can never produce an
 * elevated role (by design — see ADR 0006), this seed account must be
 * created directly against the DB before the suite runs; see
 * tests/e2e/README.md. This helper just logs in and caches the token
 * for the run. */
export async function ensureOwnerToken(request: APIRequestContext): Promise<string> {
  if (cachedOwnerToken) return cachedOwnerToken;
  const resp = await request.post(`${API_BASE}/auth/login`, {
    data: { username_or_email: "e2e_owner", password: DEFAULT_PASSWORD },
  });
  if (!resp.ok()) {
    throw new Error(
      "e2e_owner account not found. Seed it before running this suite — see " +
        "tests/e2e/README.md (reuses backend/perf/seed_users.py's approach: a " +
        "direct DB insert with role=OWNER, status=ACTIVE, username='e2e_owner', " +
        `password='${DEFAULT_PASSWORD}').`,
    );
  }
  const body = await resp.json();
  cachedOwnerToken = body.access_token;
  return cachedOwnerToken!;
}

/** Drives the actual login form (not the API) — use this whenever the
 * test cares about the logged-in UI state, not just having a token. */
export async function loginViaUI(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");
}
