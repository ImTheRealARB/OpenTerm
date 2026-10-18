import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Phase 14 (spec: docs/specs/PHASE_14.md): options, rates, futures. Every payload below is test data served by mocked routes;
 * nothing reaches the network. A part that needs a key shows KEY REQUIRED, not an error. The tables go through ResearchPanel;
 * charts and the heat map are canvas, so the tests assert on their screen-reader mirrors.
 */
const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "yahoo_options", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
const c = (key: string, title: string, kind = "text") => ({ key, title, kind, align: kind === "text" || kind === "date" ? "left" : "right" });
const payload = (title: string, sections: unknown[], headline: unknown[] = [], extra = {}) => ({
  symbol: "AAPL", title, headline, sections, notes: [], key_required: [], source: "yahoo_options", ...extra,
});

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

const CHAIN_COLS = [c("strike", "STRIKE", "price"), c("bid", "BID", "price"), c("ask", "ASK", "price"), c("oi", "OPEN INT", "int"), c("iv", "IV", "pct"), c("iv_src", "IV SRC"), c("delta", "DELTA", "num4"), c("gamma", "GAMMA", "num4")];
const OMON = payload(
  "OMON AAPL 2026-12-18",
  [
    { id: "calls", title: "CALLS", note: null, columns: CHAIN_COLS, rows: [
      { strike: 340, bid: 17.35, ask: 18, oi: 14731, iv: 0.2886, iv_src: "MID", delta: 0.5712, gamma: 0.0108 },
      { strike: 345, bid: 14.45, ask: 15.1, oi: 7170, iv: 0.2803, iv_src: "MID", delta: 0.5231, gamma: 0.0111 },
    ] },
    { id: "puts", title: "PUTS", note: null, columns: CHAIN_COLS, rows: [{ strike: 340, bid: 11.8, ask: 12.4, oi: 4006, iv: 0.2504, iv_src: "MID", delta: -0.4309, gamma: 0.0109 }] },
  ],
  [
    { label: "SPOT", value: "343.46", raw: 343.46 },
    { label: "GREEKS", value: "COMPUTED HERE (BLACK-SCHOLES, EUROPEAN), NOT VENDOR" },
  ],
  { key_required: [{ key: "TRADIER_TOKEN", what: "VENDOR GREEKS AND IV" }] },
);

test("OMON: chain rows with computed Greeks, label, KEY REQUIRED for vendor Greeks, args and errors", async ({ page }) => {
  await setup(page);
  await page.route("**/api/deriv/omon?**", (r) => {
    const u = new URL(r.request().url());
    asked.push(u.search);
    if (u.searchParams.get("date") === "2026-10-20") return r.fulfill({ status: 400, json: { error: "NOT AN EXPIRY. NEXT EXPIRIES: 2026-10-19", kind: "bad_request" } });
    return r.fulfill({ json: env(OMON) });
  });
  await run(page, "AAPL OMON 2026-12-18 OTM");
  const p = panel(page);
  await expect(p).toContainText("OMON AAPL 2026-12-18");
  await expect(p).toContainText("COMPUTED HERE (BLACK-SCHOLES, EUROPEAN), NOT VENDOR");
  await expect(p).toContainText("KEY REQUIRED: set TRADIER_TOKEN in APIKEYS");
  await expect(selected(page)).toContainText("340.00");
  await expect(selected(page)).toContainText("0.5712");
  await expect(selected(page)).toContainText("MID");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("345.00");
  await page.keyboard.press("v");
  await expect(selected(page)).toContainText("-0.4309");
  await expect.poll(() => asked[0]).toContain("symbol=AAPL");
  expect(asked[0]).toContain("date=2026-12-18");
  expect(asked[0]).toContain("moneyness=OTM");

  await run(page, "AAPL OMON 2026-10-20");
  await expect(panel(page)).toContainText("NOT AN EXPIRY");
  await run(page, "AAPL OMON DEC");
  await expect(panel(page)).toContainText("USAGE: <SYM> OMON");
});

test("PCR: ratios per expiry", async ({ page }) => {
  await setup(page);
  await page.route("**/api/deriv/pcr?**", (r) =>
    r.fulfill({
      json: env(
        payload(
          "PCR AAPL",
          [{ id: "expiry", title: "BY EXPIRY", note: null, columns: [c("expiry", "EXPIRY", "date"), c("pcr_vol", "PCR VOL", "num"), c("pcr_oi", "PCR OI", "num")], rows: [{ expiry: "2026-10-19", pcr_vol: 0.62, pcr_oi: 0.71 }] }],
          [{ label: "PCR OI", value: "0.710", raw: 0.71 }, { label: "EXPIRIES", value: "8 OF 8" }],
        ),
      ),
    }),
  );
  await run(page, "AAPL PCR");
  await expect(panel(page)).toContainText("PCR OI 0.710");
  await expect(panel(page)).toContainText("EXPIRIES 8 OF 8");
  await expect(selected(page)).toContainText("2026-10-19");
  await expect(selected(page)).toContainText("0.62");
});

test("a payload with a chart and a heat map draws them, C cycles, Shift+H J K L moves the heat cursor", async ({ page }) => {
  await setup(page);
  await page.route("**/api/deriv/pcr?**", (r) =>
    r.fulfill({
      json: env(
        payload("VIS TEST", [{ id: "t", title: "T", note: null, columns: [c("a", "A")], rows: [{ a: "row" }] }], [], {
          charts: [{ id: "smile", title: "SMILE", xlabel: "MONEYNESS", ylabel: "IV", series: [{ name: "30D", points: [[0.8, 0.31], [1, 0.27], [1.2, 0.29]] }, { name: "90D", points: [[0.8, 0.3], [1, null], [1.2, 0.28]], dash: true }] }],
          heat: { id: "surface", title: "IV SURFACE", xlabel: "MONEYNESS", ylabel: "EXPIRY", x: [0.9, 1, 1.1], y: ["2026-11-20", "2026-12-18"], z: [[0.31, 0.27, 0.29], [0.3, 0.26, null]], unit: "pct" },
        }),
      ),
    }),
  );
  await run(page, "AAPL PCR");
  const vis = panel(page).locator("[data-testid=research-visual]");
  await expect(vis).toContainText("SMILE");
  await expect(vis.locator("[data-testid=chart-smile]")).toBeVisible();
  await expect(vis.locator("[data-testid=chart-sr]")).toHaveText(/30D 3 points, 90D 2 points/);
  await expect(async () => {
    await page.keyboard.press("c");
    await expect(vis).toContainText("IV SURFACE");
  }).toPass();
  await expect(vis.locator("[data-testid=heat-sr]")).toHaveText("2026-11-20 MONEYNESS 0.9 31.0");
  await page.keyboard.press("Shift+L");
  await page.keyboard.press("Shift+J");
  await expect(vis.locator("[data-testid=heat-sr]")).toHaveText("2026-12-18 MONEYNESS 1 26.0");
  await page.keyboard.press("Shift+L");
  await expect(vis.locator("[data-testid=heat-sr]")).toHaveText("2026-12-18 MONEYNESS 1.1 no value");
});

test("OV: NOT RUNNABLE lists the missing inputs; a runnable answer shows every input with its basis", async ({ page }) => {
  await setup(page);
  await page.route("**/api/deriv/ov?**", (r) => {
    const u = new URL(r.request().url());
    asked.push(u.search);
    const runnable = u.searchParams.has("k");
    return r.fulfill({
      json: env(
        payload(
          "OV AAPL",
          [
            { id: "inputs", title: "INPUTS", note: null, columns: [c("name", "INPUT"), c("value", "VALUE"), c("basis", "BASIS")], rows: [
              { name: "IV", value: "27.00%", basis: runnable ? "typed on the command line" : "MISSING" }] },
            { id: "price", title: "MODELS", note: null, columns: [c("model", "MODEL"), c("price", "PRICE", "num4"), c("delta", "DELTA", "num4")], rows: runnable ? [{ model: "BS", price: 8.1234, delta: 0.4321 }] : [] },
          ],
          [{ label: "SPOT", value: "343.46" }],
          { status: runnable ? "RUNNABLE" : "NOT RUNNABLE: K, EXP OR T, TYPE, IV" },
        ),
      ),
    });
  });
  await run(page, "AAPL OV");
  await expect(panel(page)).toContainText("NOT RUNNABLE: K, EXP OR T, TYPE, IV");
  await run(page, "AAPL OV K=350 EXP=2026-12-18 TYPE=C IV=27");
  await expect(selected(page)).toContainText("27.00%");
  await expect.poll(() => asked.at(-1)).toContain("k=350");
  expect(asked.at(-1)).toContain("exp=2026-12-18");
  await page.keyboard.press("v");
  await expect(selected(page)).toContainText("8.1234");
  await expect(selected(page)).toContainText("0.4321");
  await run(page, "AAPL OV K");
  await expect(panel(page)).toContainText("USAGE: <SYM> OV");
});

test("OSA: payoff headline, chart and scenario heat map from one payload", async ({ page }) => {
  await setup(page);
  await page.route("**/api/deriv/osa?**", (r) =>
    r.fulfill({
      json: env(
        payload(
          "OSA AAPL",
          [{ id: "legs", title: "LEGS", note: null, columns: [c("qty", "QTY", "int"), c("type", "TYPE"), c("strike", "STRIKE", "price"), c("premium", "PREMIUM", "price")], rows: [
            { qty: 1, type: "C", strike: 270, premium: 5 }, { qty: -1, type: "C", strike: 290, premium: 2 }] }],
          [{ label: "NET DEBIT", value: "300.00", raw: 300 }, { label: "MAX PROFIT", value: "1,700.00", raw: 1700 }, { label: "MAX LOSS", value: "-300.00", raw: -300 }, { label: "BREAKEVEN", value: "273.00", raw: 273 }],
          {
            status: "RUNNABLE",
            charts: [{ id: "payoff", title: "P&L AT EXPIRY", xlabel: "SPOT", ylabel: "P&L", series: [{ name: "P&L", points: [[250, -300], [270, -300], [290, 1700], [310, 1700]] }], marks: [{ x: 273, label: "BE" }] }],
            heat: { id: "scenario", title: "SCENARIO", xlabel: "SPOT", ylabel: "IV", x: [250, 300], y: ["20.0%", "30.0%"], z: [[-300, 900], [-250, 1000]], unit: "money" },
          },
        ),
      ),
    }),
  );
  await run(page, "AAPL OSA STRAT=BULLCALL,270,290 EXP=2026-12-18 IV=25");
  await expect(panel(page)).toContainText("NET DEBIT 300.00");
  await expect(panel(page)).toContainText("MAX PROFIT 1,700.00");
  await expect(panel(page)).toContainText("BREAKEVEN 273.00");
  await expect(selected(page)).toContainText("270.00");
  const vis = panel(page).locator("[data-testid=research-visual]");
  await expect(vis).toContainText("P&L AT EXPIRY");
  await expect(vis.locator("[data-testid=chart-sr]")).toHaveText(/P&L 4 points/);
  await expect(async () => {
    await page.keyboard.press("c");
    await expect(vis.locator("[data-testid=heat-sr]")).toHaveText("20.0% SPOT 250 -300");
  }).toPass();
});
