import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Phase 17 frontend (spec: docs/specs/PHASE_17.md section D): DLVR and BRIEF with mocked routes.
 * The real backend is not involved, so these tests only prove the panels' behaviour.
 */

const now = () => Date.now() / 1000;
const SETTINGS = {
  channels: { email: false, telegram: false, webhook: false, desktop: false },
  email_to: "me@example.com",
  telegram_chat_id: "",
  brief: { enabled: false, time: "08:30", days: "mon-fri", tz: "" },
};

async function setup(page: Page) {
  const puts: Record<string, unknown>[] = [];
  const runs: string[] = [];
  const settings = JSON.parse(JSON.stringify(SETTINGS));
  const status = () => ({ email: settings.channels.email ? "KEY REQUIRED: set SMTP in APIKEYS" : "off", telegram: "off", webhook: "off" });
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/cmdhistory**", (r) => r.fulfill({ json: { items: [] } }));
  await page.route("**/api/delivery/log**", (r) =>
    r.fulfill({ json: { deliveries: [
      { id: 2, at: now(), kind: "alert", ref: "7", channel: "email", status: "failed", detail: "SMTP refused" },
      { id: 1, at: now() - 60, kind: "test", ref: "test", channel: "telegram", status: "ok", detail: null },
    ] } }));
  await page.route("**/api/delivery", (r) => {
    const req = r.request();
    if (req.method() === "PUT") {
      const patch = JSON.parse(req.postData() ?? "{}");
      puts.push(patch);
      Object.assign(settings.channels, patch.channels ?? {});
      return r.fulfill({ json: { settings, status: status() } });
    }
    return r.fulfill({ json: { settings, status: status() } });
  });
  await page.route("**/api/brief/run**", (r) => {
    runs.push(new URL(r.request().url()).search);
    return r.fulfill({ json: { brief: BRIEF, delivered: null } });
  });
  await page.route("**/api/brief", (r) => r.fulfill({ json: { brief: BRIEF } }));
  await openApp(page);
  return { puts, runs };
}

const BRIEF = {
  at: now(),
  watchlist: "main",
  sections: [
    { id: "movers", title: "Watchlist movers", source: "yahoo", age_s: 12, stale: false, error: null, lines: ["AAPL +1.2%", "MSFT -0.4%"] },
    { id: "macro", title: "Macro", source: "fred", age_s: 4000, stale: true, error: null, lines: ["10Y 4.2%"] },
    { id: "news", title: "News", source: null, age_s: null, stale: false, error: "PROVIDER DOWN", lines: [] },
  ],
};

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: Page) => page.locator('[data-panel="1"]');

test("DLVR: lists channels, Space toggles EMAIL and PUTs, L shows the log", async ({ page }) => {
  const { puts } = await setup(page);
  await run(page, "DLVR");
  const p = panel(page);
  await expect(p.locator('[data-testid="dlvr-row-email"]')).toContainText("OFF");
  for (const id of ["telegram", "webhook", "desktop", "brief"]) await expect(p.locator(`[data-testid="dlvr-row-${id}"]`)).toBeVisible();
  await expect(p.locator(".sr")).toContainText("EMAIL OFF");

  // Panel keys register after the module loads: retry the key until the PUT happens (CLAUDE.md gotcha).
  await expect(async () => {
    await page.keyboard.press("Space");
    expect(puts.length).toBeGreaterThan(0);
  }).toPass({ timeout: 5000 });
  await expect.poll(() => puts[0]).toEqual({ channels: { email: true } });
  await expect(p.locator('[data-testid="dlvr-row-email"]')).toContainText("KEY REQUIRED: set SMTP in APIKEYS");

  await page.keyboard.press("l");
  const log = p.locator('[data-testid="dlvr-log"] tbody tr');
  await expect(log).toHaveCount(2);
  await expect(log.first()).toContainText("SMTP refused"); // newest first
});

test("DLVR: Enter edits the email, a bad address is refused inline and Esc cancels", async ({ page }) => {
  await setup(page);
  await run(page, "DLVR");
  const p = panel(page);
  await expect(p.locator('[data-testid="dlvr-row-email"]')).toBeVisible();
  await expect(async () => {
    await page.keyboard.press("Enter");
    await expect(p.locator(".dlvr-in")).toBeVisible({ timeout: 300 });
  }).toPass({ timeout: 5000 });
  await page.keyboard.press("Control+a");
  await page.keyboard.type("not-an-address");
  await page.keyboard.press("Enter");
  await expect(p.locator('[data-testid="dlvr-msg"]')).toContainText("EMAIL MUST BE ONE ADDRESS");
  await page.keyboard.press("Escape");
  await expect(p.locator(".dlvr-in")).toHaveCount(0);
});

test("BRIEF: shows sections with source, age, STALE and errors; R builds now", async ({ page }) => {
  const { runs } = await setup(page);
  await run(page, "BRIEF");
  const p = panel(page);
  await expect(p).toContainText("DAILY BRIEF");
  await expect(p.locator('[data-testid="brief-movers"]')).toContainText("YAHOO · 12S");
  await expect(p.locator('[data-testid="brief-movers"]')).toContainText("AAPL +1.2%");
  await expect(p.locator('[data-testid="brief-macro"]')).toContainText("STALE");
  await expect(p.locator('[data-testid="brief-news"]')).toContainText("ERR: PROVIDER DOWN");

  await expect(async () => {
    await page.keyboard.press("r");
    expect(runs.length).toBeGreaterThan(0);
  }).toPass({ timeout: 5000 });
  expect(runs[0]).toBe("?send=0");
});
