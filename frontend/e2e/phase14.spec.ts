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

test("OVDV / SKEW / HIVG: surface heat map with empty cells, skew table, realized vs implied headline", async ({ page }) => {
  await setup(page);
  await page.route("**/api/deriv/ovdv?**", (r) =>
    r.fulfill({
      json: env(
        payload("OVDV AAPL", [{ id: "fit", title: "FITTED SMILE PER EXPIRY", note: null, columns: [c("expiry", "EXPIRY", "date"), c("atm_iv", "ATM IV", "pct")], rows: [{ expiry: "2026-10-19", atm_iv: 0.255 }] }],
          [{ label: "FIT", value: "FIT: QUADRATIC IN LOG-MONEYNESS, NOT SVI" }],
          { heat: { id: "surface", title: "IV SURFACE", xlabel: "K / FORWARD", ylabel: "EXPIRY", x: [0.9, 1, 1.1], y: ["2026-10-19"], z: [[null, 0.255, null]], unit: "pct" } }),
      ),
    }),
  );
  await run(page, "AAPL OVDV");
  const p = panel(page);
  await expect(p).toContainText("NOT SVI");
  await expect(p.locator("[data-testid=heat-sr]")).toHaveText("2026-10-19 K / FORWARD 0.9 no value");
  await page.keyboard.press("Shift+L");
  await expect(p.locator("[data-testid=heat-sr]")).toHaveText("2026-10-19 K / FORWARD 1 25.5");

  await page.route("**/api/deriv/skew?**", (r) =>
    r.fulfill({
      json: env(
        payload("SKEW AAPL", [{ id: "skew", title: "SKEW BY EXPIRY", note: null, columns: [c("expiry", "EXPIRY", "date"), c("rr25", "RR25", "pct"), c("iv_c25", "25D CALL IV", "pct")], rows: [{ expiry: "2026-10-19", rr25: null, iv_c25: null }, { expiry: "2026-11-20", rr25: -0.045, iv_c25: 0.26 }] }], []),
      ),
    }),
  );
  await run(page, "AAPL SKEW");
  await expect(selected(page)).toContainText("2026-10-19");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("-4.50%");

  await page.route("**/api/deriv/hivg?**", (r) =>
    r.fulfill({
      json: env(
        payload("HIVG AAPL", [{ id: "rv", title: "REALIZED VOL", note: null, columns: [c("window", "DAYS", "int"), c("cc_vol", "CLOSE-CLOSE", "pct")], rows: [{ window: 30, cc_vol: 0.21 }] }],
          [{ label: "IV30", value: "26.0%", raw: 0.26 }, { label: "IV RANK", value: "NOT AVAILABLE: 1 LOCAL SNAPSHOT SINCE 2026-10-18 (NEEDS 20)" }]),
      ),
    }),
  );
  await run(page, "AAPL HIVG");
  await expect(panel(page)).toContainText("IV30 26.0%");
  await expect(panel(page)).toContainText("NOT AVAILABLE: 1 LOCAL SNAPSHOT");
});


test("RATES: EUR curve table and SPRD spread table through the research panel; no argument stays the US panel", async ({ page }) => {
  await setup(page);
  const ratesAsked: string[] = [];
  const curveCols = [c("tenor", "TENOR"), c("years", "YEARS", "num"), c("yield", "YIELD %", "num4"), c("d1", "1D BP", "bp"), c("d5", "5D BP", "bp")];
  await page.route("**/api/rates/curve?**", (r) => {
    ratesAsked.push(new URL(r.request().url()).search);
    return r.fulfill({
      json: env(
        payload("RATES EUR", [{ id: "curve", title: "EUR CURVE", note: null, columns: curveCols, rows: [
          { tenor: "3M", years: 0.25, yield: 2.5838, d1: 3.8, d5: 5.3 },
          { tenor: "10Y", years: 10, yield: 3.3904, d1: -12, d5: -12.9 },
        ] }], [{ label: "CURVE", value: "ECB EURO AREA AAA GOVERNMENT SPOT CURVE" }, { label: "AS OF", value: "2026-10-15" }], { symbol: "EUR", source: "ecb" }),
        { source: "ecb" },
      ),
    });
  });
  await page.route("**/api/rates/spreads?**", (r) =>
    r.fulfill({
      json: env(
        payload("RATES SPRD", [{ id: "oas", title: "CREDIT SPREADS (OAS)", note: null, columns: [c("series", "FRED ID"), c("name", "OPTION-ADJUSTED SPREAD"), c("bp", "OAS BP", "bp"), c("date", "AS OF", "date")], rows: [
          { series: "BAMLC0A0CM", name: "US CORPORATE (INVESTMENT GRADE)", bp: 84, date: "2026-10-15" },
          { series: "BAMLH0A0HYM2", name: "US HIGH YIELD", bp: 323, date: "2026-10-15" },
        ] }], [{ label: "AS OF", value: "2026-10-15" }], { symbol: null, source: "fred_oas" }),
        { source: "fred_oas" },
      ),
    }),
  );
  await run(page, "RATES EUR");
  const p = panel(page);
  await expect(p).toContainText("ECB EURO AREA AAA GOVERNMENT SPOT CURVE");
  await expect(selected(page)).toContainText("3M");
  await expect(selected(page)).toContainText("2.5838");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("3.3904");
  await expect.poll(() => ratesAsked[0]).toContain("ccy=EUR");

  await run(page, "RATES NS EUR");
  await expect.poll(() => ratesAsked.some((q) => q.includes("fit=NS"))).toBe(true);

  await run(page, "RATES SPRD");
  await expect(p).toContainText("US CORPORATE (INVESTMENT GRADE)");
  await expect(selected(page)).toContainText("BAMLC0A0CM");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("323");

  await run(page, "RATES XYZ");
  await expect(p).toContainText("USAGE: RATES [EUR|GBP|CAD|JPY|SPRD|AUCT|NS");
});

test("CT / YAS / FXFA: futures curve rows, a calculator that is NOT RUNNABLE, and typed rates reaching the API", async ({ page }) => {
  await setup(page);
  const fut: string[] = [];
  await page.route("**/api/deriv/ct?**", (r) => {
    fut.push(new URL(r.request().url()).search);
    return r.fulfill({
      json: env(
        payload("CT CL", [{ id: "contracts", title: "CL CONTRACTS", note: null, columns: [c("symbol", "SYMBOL"), c("contract", "CONTRACT"), c("price", "PRICE", "price"), c("roll_yield", "ROLL YIELD (ANN.)", "pct")], rows: [
          { symbol: "CLX26.NYM", contract: "NOV 2026", price: 97.5, roll_yield: null },
          { symbol: "CLZ26.NYM", contract: "DEC 2026", price: 99.02, roll_yield: -0.1842 },
        ] }], [{ label: "SHAPE", value: "MIXED" }], { symbol: "CL", source: "yahoo_futures:fixture" }),
        { source: "yahoo_futures:fixture" },
      ),
    });
  });
  await page.route("**/api/deriv/yas?**", (r) =>
    r.fulfill({ json: env(payload("YAS BOND YIELD ANALYSIS", [{ id: "inputs", title: "INPUTS", note: null, columns: [c("name", "INPUT"), c("value", "VALUE")], rows: [{ name: "CPN", value: "4.5000%" }] }], [], { status: "NOT RUNNABLE: MISSING MAT, PX OR YLD", symbol: "YAS" })) }),
  );
  await page.route("**/api/deriv/fxfa?**", (r) => {
    fut.push(new URL(r.request().url()).search);
    return r.fulfill({ json: env(payload("FXFA EURUSD", [{ id: "forwards", title: "FORWARDS", note: null, columns: [c("tenor", "TENOR"), c("forward", "FORWARD", "num4")], rows: [{ tenor: "1W", forward: 1.1252 }] }], [{ label: "SPOT", value: "1.1244", raw: 1.1244 }], { symbol: "EURUSD" })) });
  });
  await run(page, "CT CL");
  await expect(panel(page)).toContainText("MIXED");
  await expect(selected(page)).toContainText("NOV 2026");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("99.02");
  await expect.poll(() => fut[0]).toContain("root=CL");

  await run(page, "YAS CPN=4.5");
  await expect(panel(page)).toContainText("NOT RUNNABLE: MISSING MAT, PX OR YLD");

  await run(page, "FXFA EURUSD R1=2 R2=4");
  await expect(selected(page)).toContainText("1W");
  await expect.poll(() => fut.at(-1)).toContain("pair=EURUSD");
  expect(fut.at(-1)).toContain("r1=2");
  await run(page, "CT CL NG");
  await expect(panel(page)).toContainText("USAGE: CT <ROOT>");
});

test("OSA -> BT MKT=options: B hands over the shown structure; nothing is defaulted; no OSA structure says so", async ({ page }) => {
  await setup(page);
  const posted: Record<string, unknown>[] = [];
  await page.route("**/api/bt/run", (r) => {
    posted.push(r.request().postDataJSON());
    return r.fulfill({ status: 400, json: { error: "NOT RUNNABLE: MISSING open_date, exercise_style", kind: "bad_request" } });
  });
  await page.route("**/api/deriv/osa?**", (r) =>
    r.fulfill({
      json: env(
        payload("OSA AAPL", [
          { id: "legs", title: "LEGS", note: null, columns: [c("qty", "QTY", "int"), c("type", "TYPE"), c("strike", "STRIKE", "price")], rows: [
            { qty: 1, type: "C", strike: 270 }, { qty: -1, type: "C", strike: 290 }] },
          { id: "inputs", title: "INPUTS", note: null, columns: [c("name", "INPUT"), c("value", "VALUE")], rows: [
            { name: "R", value: "4.10%", rate: 0.041 }, { name: "MULT", value: "100" }] },
        ], [], { status: "RUNNABLE" }),
      ),
    }),
  );
  await run(page, "AAPL OSA STRAT=BULLCALL,270,290 EXP=2026-12-18 IV=25");
  await expect(selected(page)).toContainText("270.00");
  await expect(async () => {
    await page.keyboard.press("b");
    await expect(panel(page)).toContainText("NOT RUNNABLE: MISSING open_date, exercise_style");
  }).toPass();
  const body = posted.at(-1)!;
  expect(body).toMatchObject({ symbols: ["AAPL"], options: { engine: "options" } });
  expect(body.rule).toBeUndefined();
  expect(body.structure).toEqual({
    legs: [{ type: "call", strike: 270, qty: 1, expiry: "2026-12-18" }, { type: "call", strike: 290, qty: -1, expiry: "2026-12-18" }],
    risk_free_rate: 0.041, contract_multiplier: 100,
  });
  await run(page, "BT AAPL MKT=options OPEN=2026-06-01 STYLE=european");
  await expect.poll(() => posted.length).toBe(2);
  expect(posted.at(-1)!.structure).toMatchObject({ open_date: "2026-06-01", exercise_style: "european" });
  await run(page, "BT MSFT MKT=options");
  await expect(panel(page)).toContainText("NO OSA STRUCTURE");
  expect(posted.length).toBe(2);
});
