import { test, expect } from "@playwright/test";
import { createActiveUser, loginViaUI, uniqueUsername, DEFAULT_PASSWORD } from "./helpers";

test.describe("Registration and login", () => {
  test("register shows a pending-approval notice on first login attempt", async ({
    page,
  }) => {
    const username = uniqueUsername("newreg");
    await page.goto("/register");
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Email").fill(`${username}@example.com`);
    await page.getByLabel("Password").fill(DEFAULT_PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();

    // Redirects to /login with a "registered" notice.
    await expect(page).toHaveURL("/login");
    await expect(page.getByText(/account created/i)).toBeVisible();

    // Logging in before approval must surface the pending-approval state,
    // not a generic error.
    await page.getByLabel("Username or email").fill(username);
    await page.getByLabel("Password").fill(DEFAULT_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText(/pending manager approval/i)).toBeVisible();
    await expect(page).toHaveURL("/login");
  });

  test("registration rejects a duplicate username", async ({ page, request }) => {
    const { username } = await createActiveUser(request);
    await page.goto("/register");
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Email").fill(`${username}_dup@example.com`);
    await page.getByLabel("Password").fill(DEFAULT_PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.locator(".auth-notice.error")).toBeVisible();
  });

  test("login with wrong password shows an error, not a crash", async ({ page, request }) => {
    const { username } = await createActiveUser(request);
    await page.goto("/login");
    await page.getByLabel("Username or email").fill(username);
    await page.getByLabel("Password").fill("definitely-wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.locator(".auth-notice.error")).toBeVisible();
    await expect(page).toHaveURL("/login");
  });

  test("an approved user can log in and reaches the chat workspace", async ({
    page,
    request,
  }) => {
    const { username, password } = await createActiveUser(request);
    await loginViaUI(page, username, password);
    await expect(page.locator(".chat-pane, .composer")).toBeVisible();
  });

  test("submit button shows a loading state while signing in", async ({ page, request }) => {
    const { username, password } = await createActiveUser(request);
    await page.goto("/login");
    await page.getByLabel("Username or email").fill(username);
    await page.getByLabel("Password").fill(password);
    const submit = page.getByRole("button", { name: "Sign in" });
    await submit.click();
    // The submit button disables and shows a spinner while the request
    // is in flight (LoginPage.tsx: `submitting` state).
    await expect(submit).toBeDisabled();
  });

  test("logging out returns to the login page and blocks direct access to chat", async ({
    page,
    request,
  }) => {
    const { username, password } = await createActiveUser(request);
    await loginViaUI(page, username, password);
    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL("/login");
    await page.goto("/");
    await expect(page).toHaveURL("/login");
  });
});
