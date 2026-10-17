import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Phase 13 (spec: docs/specs/PHASE_13.md): equity research gaps. Every payload below is test data served by mocked
 * routes; nothing reaches the network. A section needing a key shows KEY REQUIRED, not an error.
 */
const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "yahoo_research", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
const c = (key: string, title: string, kind = "text") => ({ key, title, kind, align: kind === "text" || kind === "date" ? "left" : "right" });
const payload = (title: string, sections: unknown[], headline: unknown[] = [], extra = {}) => ({
  symbol: "AAPL", title, headline, sections, notes: [], key_required: [], source: "yahoo_research", ...extra,
});

const EE = payload(
  "EE AAPL · ESTIMATES",
  [
    {
      id: "eps", title: "EPS CONSENSUS", note: null,
      columns: [c("period", "PERIOD"), c("end", "ENDS", "date"), c("avg", "AVG", "num"), c("analysts", "ANALYSTS", "int"), c("growth", "GROWTH", "pct")],
      rows: [
        { period: "CURRENT QTR", end: "2026-09-30", avg: 1.97842, analysts: 27, growth: 0.0694 },
        { period: "NEXT QTR", end: "2026-12-31", avg: 2.7, analysts: 26, growth: -0.01 },
      ],
    },
    {
      id: "revenue", title: "REVENUE CONSENSUS", note: null,
      columns: [c("period", "PERIOD"), c("avg", "AVG", "money")],
      rows: [{ period: "CURRENT QTR", avg: 113626875100 }],
    },
  ],
  [{ label: "CURRENCY", value: "USD" }],
);

const asked: string[] = [];

async function setup(page: Page) {
  asked.length = 0;
  await page.routeWebSocket(/\/ws$/, (route) =>
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    }),
  );
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    const q = (s: string) => ({ symbol: s, name: s, currency: "USD", exchange: "X", tz: "America/New_York", price: 100, prev_close: 99, change: 1, change_pct: 1, open: null, high: 101, low: 98, volume: 1, high_52w: null, low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now() });
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s) => [s, env(q(s), { source: "yahoo" })])) } });
  });
  await openApp(page);
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const selected = (page: Page, id = 1) => panel(page, id).locator(".grid .sr");

test("EE: sections, signed growth, section keys, source and unknown-symbol error", async ({ page }) => {
  await setup(page);
  await page.route("**/api/research/ee?**", (r) => {
    const u = new URL(r.request().url());
    asked.push(u.search);
    if (u.searchParams.get("symbol") === "ZZZZ") return r.fulfill({ status: 404, json: { error: "NO DATA FOR SYMBOL", kind: "not_found" } });
    return r.fulfill({ json: env(EE) });
  });
  await run(page, "AAPL EE");
  const p = panel(page);
  await expect(p).toContainText("EE AAPL · ESTIMATES");
  await expect(p).toContainText("YAHOO_RESEARCH");
  await expect(p).toContainText("CURRENCY USD");
  await expect(p).toContainText("[1] EPS CONSENSUS [2] REVENUE CONSENSUS");
  await expect(selected(page)).toContainText("CURRENT QTR");
  await expect(selected(page)).toContainText("1.98");
  await expect(selected(page)).toContainText("+6.94%");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("NEXT QTR");
  await expect(selected(page)).toContainText("-1.00%");
  await page.keyboard.press("v");
  await expect(selected(page)).toContainText("113.63B");
  await page.keyboard.press("1");
  await expect(selected(page)).toContainText("CURRENT QTR");
  expect(asked[0]).toContain("symbol=AAPL");

  await run(page, "ZZZZ EE");
  await expect(panel(page)).toContainText("NO DATA FOR SYMBOL");
});

test("ANR: a stale answer says STALE with its age; a down provider says so", async ({ page }) => {
  await setup(page);
  await page.route("**/api/research/anr?**", (r) => {
    const sym = new URL(r.request().url()).searchParams.get("symbol");
    if (sym === "MSFT") return r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "yahoo_research: unavailable (timeout)" } });
    return r.fulfill({
      json: env(
        payload(
          "ANR AAPL · ANALYST RATINGS",
          [{ id: "trend", title: "RECOMMENDATION MIX (ANALYSTS)", note: null, columns: [c("period", "PERIOD"), c("buy", "BUY", "int")], rows: [{ period: "THIS MONTH", buy: 19 }] }],
          [{ label: "TARGET MEAN", value: "329.38", raw: 329.3759 }],
        ),
        { stale: true, age_s: 600 },
      ),
    });
  });
  await run(page, "AAPL ANR");
  await expect(panel(page)).toContainText("TARGET MEAN 329.38");
  await expect(panel(page)).toContainText("STALE 10M");
  await run(page, "MSFT ANR");
  await expect(panel(page)).toContainText("PROVIDER DOWN");
});

test("MGMT: officers table and the board note; empty proxy section says why", async ({ page }) => {
  await setup(page);
  await page.route("**/api/research/mgmt?**", (r) =>
    r.fulfill({
      json: env(
        payload(
          "MGMT AAPL · MANAGEMENT",
          [
            { id: "officers", title: "OFFICERS", note: null, columns: [c("name", "NAME"), c("pay", "TOTAL PAY", "money")], rows: [{ name: "Mr. Timothy D. Cook", pay: 16759518 }] },
            { id: "proxy", title: "PROXY STATEMENTS (DEF 14A)", note: "NO PROXY STATEMENT IN THE RECENT FILINGS FEED", columns: [c("date", "FILED", "date")], rows: [] },
          ],
          [{ label: "EMPLOYEES", value: "150,000" }],
          { notes: ["BOARD MEMBERS ARE IN THE PROXY STATEMENT"] },
        ),
      ),
    }),
  );
  await run(page, "AAPL MGMT");
  await expect(selected(page)).toContainText("Mr. Timothy D. Cook");
  await expect(selected(page)).toContainText("16.76M");
  await expect(panel(page)).toContainText("BOARD MEMBERS ARE IN THE PROXY STATEMENT");
  await page.keyboard.press("v");
  await expect(panel(page)).toContainText("NO PROXY STATEMENT IN THE RECENT FILINGS FEED");
});

test("a section that needs a key shows KEY REQUIRED next to the data", async ({ page }) => {
  await setup(page);
  await page.route("**/api/research/ee?**", (r) =>
    r.fulfill({ json: env(payload("EE AAPL · ESTIMATES", EE.sections, [], { key_required: [{ key: "FINNHUB_API_KEY", what: "SURPRISE CROSS-CHECK" }] })) }),
  );
  await run(page, "AAPL EE");
  await expect(panel(page)).toContainText("KEY REQUIRED: set FINNHUB_API_KEY in APIKEYS");
  await expect(selected(page)).toContainText("CURRENT QTR");
});

test("a missing key from the backend (424) shows the shared KEY REQUIRED line", async ({ page }) => {
  await setup(page);
  await page.route("**/api/research/ee?**", (r) =>
    r.fulfill({ status: 424, json: { error: "KEY REQUIRED", kind: "key_required", key: "FINNHUB", detail: "KEY REQUIRED: set FINNHUB in APIKEYS" } }),
  );
  await run(page, "AAPL EE");
  await expect(panel(page)).toContainText("KEY REQUIRED");
});
