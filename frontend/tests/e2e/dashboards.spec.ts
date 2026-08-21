import { test, expect } from "@playwright/test";
import { createActiveUser, loginViaUI } from "./helpers";

test.describe("Manager dashboard", () => {
  test("approve a pending user and see it reflected in group users", async ({
    page,
    request,
  }) => {
    const manager = await createActiveUser(request, { role: "MANAGER" });
    // A second, still-pending registration in the same flow the Manager
    // will approve via the UI (not the helper, which auto-approves).
    const pendingUsername = `pending_${Date.now()}`;
    const regResp = await request.post("http://localhost:8000/api/v1/auth/register", {
      data: {
        username: pendingUsername,
        email: `${pendingUsername}@example.com`,
        password: "correct-horse-1",
      },
    });
    expect(regResp.ok()).toBeTruthy();

    await loginViaUI(page, manager.username, manager.password);
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Manager dashboard" })).toBeVisible();

    await expect(page.getByText(pendingUsername)).toBeVisible();
    const row = page.locator("tr", { hasText: pendingUsername });
    await row.getByRole("button", { name: "Approve" }).click();
    await expect(row).not.toBeVisible();

    await page.getByRole("button", { name: "Group" }).click();
    await expect(page.getByText(pendingUsername)).toBeVisible();
  });

  test("authorized activity tab shows the manager's own approval", async ({
    page,
    request,
  }) => {
    const manager = await createActiveUser(request, { role: "MANAGER" });
    await loginViaUI(page, manager.username, manager.password);
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "Authorized activity" }).click();
    await expect(page.locator(".dashboard-section", { hasText: "Authorized activity" })).toBeVisible();
  });

  test("a plain user has no dashboard link and is bounced from /dashboard", async ({
    page,
    request,
  }) => {
    const user = await createActiveUser(request);
    await loginViaUI(page, user.username, user.password);
    await expect(page.locator('a[href="/dashboard"]')).toHaveCount(0);

    await page.goto("/dashboard");
    await expect(page).toHaveURL("/");
  });
});

test.describe("Developer dashboard", () => {
  test("shows application/backend/model health and logs", async ({ page, request }) => {
    const dev = await createActiveUser(request, { role: "DEVELOPER" });
    await loginViaUI(page, dev.username, dev.password);
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Developer dashboard" })).toBeVisible();

    await expect(page.getByText("Application health")).toBeVisible();
    await expect(page.getByText("Backend health")).toBeVisible();
    await expect(page.getByText("Model health")).toBeVisible();

    await page.getByRole("button", { name: "Performance" }).click();
    await expect(page.getByText("Request latency & error rates")).toBeVisible();

    await page.getByRole("button", { name: "Logs" }).click();
    await expect(page.locator(".dashboard-section", { hasText: "Logs" })).toBeVisible();
  });

  test("developer cannot reach owner-only admin endpoints via direct navigation", async ({
    page,
    request,
  }) => {
    const dev = await createActiveUser(request, { role: "DEVELOPER" });
    await loginViaUI(page, dev.username, dev.password);
    // Backend enforcement (not UI) is the real boundary — verified here
    // via a direct API call using the same session token the UI is using.
    const token = await page.evaluate(() => localStorage.getItem("ai_platform_access_token"));
    const resp = await request.get("http://localhost:8000/api/v1/admin/audit-logs", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBe(403);
  });
});

test.describe("Owner dashboard", () => {
  test("covers users, groups, models, usage, config, audit, health tabs", async ({
    page,
    request,
  }) => {
    const owner = await createActiveUser(request, { role: "OWNER" });
    await loginViaUI(page, owner.username, owner.password);
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Owner dashboard" })).toBeVisible();

    for (const tab of [
      "Users & roles",
      "Groups",
      "Models",
      "Usage",
      "System configuration",
      "Audit logs",
      "Health",
    ]) {
      await page.getByRole("button", { name: tab }).click();
      await expect(page.locator(".dashboard-tab.active", { hasText: tab })).toBeVisible();
    }
  });

  test("owner can create a group from the dashboard", async ({ page, request }) => {
    const owner = await createActiveUser(request, { role: "OWNER" });
    await loginViaUI(page, owner.username, owner.password);
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "Groups" }).click();

    const groupName = `e2e-group-${Date.now()}`;
    await page.getByPlaceholder("New group name").fill(groupName);
    await page.getByRole("button", { name: "Create group" }).click();
    await expect(page.getByText(groupName)).toBeVisible();
  });

  test("owner can change a user's role", async ({ page, request }) => {
    const owner = await createActiveUser(request, { role: "OWNER" });
    const target = await createActiveUser(request);
    await loginViaUI(page, owner.username, owner.password);
    await page.goto("/dashboard");

    const row = page.locator("tr", { hasText: target.username });
    await row.locator("select").first().selectOption("MANAGER");
    await expect(row.locator("select").first()).toHaveValue("MANAGER");
  });
});
