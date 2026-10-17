import type { Page } from "@playwright/test";

/**
 * Opens the app and waits until it is ready. Register page.route / routeWebSocket mocks first.
 * Every test gets a fresh browser context, so localStorage starts empty: no clear-and-reload needed.
 */
export async function openApp(page: Page) {
  await page.goto("/");
  await page.waitForFunction(() => window.__openterm_perf?.ready);
}
