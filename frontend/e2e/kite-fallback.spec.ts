import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Kite follow-up (2026-11-05): when the Kite login has expired the backend answers from Yahoo and says why in `fallback_notes`.
 * Q, DES and HIST must show that reason (GP already did); a quote that came straight from the first source shows no warning.
 * All data below is test data served by mocked routes.
 */
const now = () => Date.now() / 1000;
const NOTE = "KITE LOGIN EXPIRED: run KITE LOGIN";
const fallback = { fallback_from: ["kite"], fallback_notes: { kite: NOTE } };
const env = (data: unknown, extra = {}) => ({ data, source: "yahoo", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });

const quote = (s: string) => ({
  symbol: s, name: s, currency: "INR", exchange: "NSE", tz: "Asia/Kolkata", price: 1300, prev_close: 1310, change: -10, change_pct: -0.76,
  open: null, high: 1320, low: 1290, volume: 1000, high_52w: null, low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now(),
});

async function setup(page: Page, extra: object) {
  await page.routeWebSocket(/\/ws$/, (route) =>
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    }),
  );
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s) => [s, env(quote(s), extra)])) } });
  });
  await page.route("**/api/history?**", (r) => {
    const u = new URL(r.request().url());
    const T = [1, 2, 3].map((i) => 1_700_000_000 + i * 86400);
    const c = [1290, 1300, 1310];
    const data = { symbol: u.searchParams.get("symbol"), range: "1mo", interval: "1d", currency: "INR", exchange: "NSE", tz: "Asia/Kolkata", t: T, o: c, h: c, l: c, c, v: [1, 2, 3], source: "yahoo", as_of: now(), adj: null };
    return r.fulfill({ json: env(data, extra) });
  });
  await page.route("**/api/profile?**", (r) => r.fulfill({ status: 404, json: { error: "NO DATA FOR SYMBOL", kind: "not_found" } }));
  await openApp(page);
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: Page) => page.locator('[data-panel="1"]');
const SAYS = "KITE LOGIN EXPIRED: RUN KITE LOGIN, VIA FALLBACK";

test("Q shows why Kite was skipped", async ({ page }) => {
  await setup(page, fallback);
  await run(page, "Q RELIANCE.NS");
  await expect(panel(page)).toContainText(SAYS);
});

test("Q shows no warning when the first source answered", async ({ page }) => {
  await setup(page, {});
  await run(page, "Q RELIANCE.NS");
  await expect(panel(page)).toContainText("QUOTE MONITOR");
  await expect(panel(page)).not.toContainText("FALLBACK");
});

test("DES shows why Kite was skipped for the quote", async ({ page }) => {
  await setup(page, fallback);
  await run(page, "RELIANCE.NS DES");
  await expect(panel(page)).toContainText(`QUOTE: ${SAYS}`);
});

test("HIST shows why Kite was skipped", async ({ page }) => {
  await setup(page, fallback);
  await run(page, "RELIANCE.NS HIST");
  await expect(panel(page)).toContainText(SAYS);
});
