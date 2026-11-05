import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Phase 17 frontend (spec: docs/specs/PHASE_17.md section D): DLVR and BRIEF with mocked routes.
 * The real backend is not involved, so these tests only prove the panels' behaviour.
 */

const now = () => Date.now() / 1000;
const SETTINGS = {
  channels: { email: false, telegram: false, webhook: false, desktop: false },
  // Phase 20 rule 5: the browser only gets masked hints, never the address or chat id
  recipients: { email: { configured: true, hint: "m•••@example.com" }, telegram: { configured: false, hint: "" } },
  daily_cap: 50,
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
  // Phase 20: Telegram pairing. First check says "not yet", the second says paired.
  let checks = 0;
  await page.route("**/api/delivery/telegram/pair/start", (r) =>
    r.fulfill({ json: { bot: "OpenTermBot", link: "https://t.me/OpenTermBot", code: "OT-123456", expires_in: 600 } }));
  await page.route("**/api/delivery/telegram/pair/check", (r) => {
    checks += 1;
    if (checks >= 2) settings.recipients.telegram = { configured: true, hint: "chat linked" };
    return r.fulfill({ json: { paired: checks >= 2 } });
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

test("DLVR: P shows the bot link and code, C checks, then the row shows only a hint", async ({ page }) => {
  await setup(page);
  await run(page, "DLVR");
  const p = panel(page);
  await expect(p.locator('[data-testid="dlvr-row-telegram"]')).toBeVisible();
  await expect(async () => {
    await page.keyboard.press("p");
    await expect(p.locator('[data-testid="dlvr-pair"]')).toBeVisible({ timeout: 300 });
  }).toPass({ timeout: 5000 });
  await expect(p.locator('[data-testid="dlvr-pair-code"]')).toHaveText("OT-123456");
  await expect(p.locator('[data-testid="dlvr-pair"] a')).toHaveAttribute("href", "https://t.me/OpenTermBot");
  await page.keyboard.press("c");
  await expect(p.locator('[data-testid="dlvr-msg"]')).toContainText("CODE NOT SEEN YET");
  await page.keyboard.press("c");
  await expect(p.locator('[data-testid="dlvr-msg"]')).toContainText("TELEGRAM PAIRED");
  await expect(p.locator('[data-testid="dlvr-pair"]')).toHaveCount(0);
  await expect(p.locator('[data-testid="dlvr-row-telegram"]')).toContainText("chat linked");
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
