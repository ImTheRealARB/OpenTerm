import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Phase 15 (spec: docs/specs/PHASE_15.md): RISK, PORT OPT, PORT ATTR, FACT, QL, ALPHA, CORR REGIME and the KITE status panel. Every payload
 * is test data served by mocked routes; nothing reaches the network. Each function is a job (`POST /api/quant/{fn}`) whose result is the
 * table payload ResearchPanel renders; a job that is still running shows its progress and finishes through `GET /api/jobs/{id}` (the mocked
 * socket sends no J frames, so this also covers the polling fallback). Every test was marked test.fail() until its build step landed
 * (step 3: RISK, OPT, ATTR; 4: FACT, QL; 5: ALPHA, REGIME; 7: KITE); the markers are gone.
 */
const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "yahoo", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
const c = (key: string, title: string, kind = "text") => ({ key, title, kind, align: kind === "text" || kind === "date" ? "left" : "right" });
const payload = (title: string, sections: unknown[], headline: unknown[] = [], extra = {}) => ({
  symbol: null, title, headline, sections, notes: [], key_required: [], source: "yahoo", ...extra,
});
const job = (result: unknown, extra = {}) => ({ id: "j1", kind: "x", label: "x", state: "done", progress: 1, msg: "", cached: false, error: null, result, ...extra });

const bodies: Record<string, unknown[]> = {};
const puts: { url: string; body: unknown }[] = [];

async function setup(page: Page) {
  for (const k of Object.keys(bodies)) delete bodies[k];
  puts.length = 0;
  await page.routeWebSocket(/\/ws$/, (route) =>
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    }),
  );
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    const q = (s: string) => ({ symbol: s, name: s, currency: "USD", exchange: "X", tz: "America/New_York", price: 100, prev_close: 99, change: 1, change_pct: 1, open: null, high: 101, low: 98, volume: 1, high_52w: null, low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now() });
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s) => [s, env(q(s))])) } });
  });
  await openApp(page);
}

async function mockQuant(page: Page, fn: string, answer: (body: unknown) => unknown) {
  await page.route(`**/api/quant/${fn}`, (r) => {
    const body = r.request().postDataJSON();
    (bodies[fn] ||= []).push(body);
    return r.fulfill({ json: answer(body) });
  });
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const selected = (page: Page, id = 1) => panel(page, id).locator(".grid .sr");

const RISK = payload(
  "RISK T",
  [
    { id: "var", title: "VALUE AT RISK", note: null, columns: [c("method", "METHOD"), c("conf", "CONF", "int"), c("var_pct", "VAR", "pct"), c("var_money", "VAR $", "money"), c("es_pct", "ES", "pct")], rows: [
      { method: "HIST", conf: 95, var_pct: 0.0164, var_money: 4920, es_pct: 0.0211 }, { method: "EVT", conf: 99, var_pct: 0.0301, var_money: 9030, es_pct: 0.0388 }] },
    { id: "stress", title: "STRESS REPLAYS", note: "COVERAGE IS THE WEIGHT WITH HISTORY OVER THE WINDOW", columns: [c("id", "ID"), c("name", "SCENARIO"), c("coverage", "COVERAGE", "pct"), c("ret", "RETURN", "pct")], rows: [
      { id: "2008", name: "2008 CRISIS", coverage: 0.6, ret: -0.31 }, { id: "2020", name: "2020 CRASH", coverage: 1, ret: -0.2 }] },
  ],
  [{ label: "VALUE", value: "300,000", raw: 300000 }, { label: "VOL (ANN)", value: "14.2%", raw: 0.142 }, { label: "DATA", value: "SYNTHETIC TEST DATA" }],
  { charts: [{ id: "equity", title: "CUMULATIVE RETURN (CURRENT WEIGHTS HELD CONSTANT)", xlabel: "DAY", ylabel: "x", series: [{ name: "PORT", points: [[0, 1], [1, 1.01], [2, 1.02]] }] }] },
);

test.describe("Phase 15", () => {
  test("RISK: the portfolio and typed params go to the job, VaR and stress rows show, bad args print usage", async ({ page }) => {
    await setup(page);
    await mockQuant(page, "risk", () => job(env(RISK)));
    await run(page, "RISK T RANGE=1y CONF=99 HOR=5");
    const p = panel(page);
    await expect(p).toContainText("RISK T");
    await expect(p).toContainText("VOL (ANN) 14.2%");
    await expect(p).toContainText("SYNTHETIC TEST DATA");
    await expect(selected(page)).toContainText("HIST");
    await expect(selected(page)).toContainText("1.64");
    await page.keyboard.press("v");
    await expect(selected(page)).toContainText("2008 CRISIS");
    await expect.poll(() => bodies.risk?.[0]).toEqual({ portfolio: "T", range: "1y", conf: 99, hor: 5 });
    await run(page, "RISK T FOO=1");
    await expect(panel(page)).toContainText("USAGE: RISK");
  });

  test("RISK: a NOT RUNNABLE answer lists what is missing", async ({ page }) => {
    await setup(page);
    await mockQuant(page, "risk", () => job(env(payload("RISK", [], [], { status: "NOT RUNNABLE: PORTFOLIO (A, B)" }))));
    await run(page, "RISK");
    await expect(panel(page)).toContainText("NOT RUNNABLE: PORTFOLIO (A, B)");
  });

  test("PORT OPT: the preview shows trades and before/after, A saves <NAME>.OPT without touching the original", async ({ page }) => {
    await setup(page);
    await page.route("**/api/portfolios/**", (r) => {
      if (r.request().method() === "PUT") {
        puts.push({ url: new URL(r.request().url()).pathname, body: r.request().postDataJSON() });
        return r.fulfill({ json: { name: "T.OPT", positions: [], base: null, updated_at: now() } });
      }
      return r.fulfill({ json: { name: "T", positions: [{ symbol: "SYN0001", qty: 100, cost: 100, currency: null, notes: null }], base: "INR", updated_at: now() } });
    });
    const trades = { id: "trades", title: "TRADES", note: null, columns: [c("symbol", "SYMBOL"), c("qty_now", "QTY NOW", "int"), c("w_now", "NOW", "pct"), c("w_target", "TARGET", "pct"), c("shares", "TRADE SH", "int"), c("price", "PRICE", "price")], rows: [
      { symbol: "SYN0001", qty_now: 100, w_now: 0.5, w_target: 0.4, shares: -20, price: 101.5, ccy: "INR" }, { symbol: "SYN0002", qty_now: 100, w_now: 0.5, w_target: 0.6, shares: 15, price: 98.25, ccy: null }] };
    await mockQuant(page, "opt", () => job(env(payload("PORT OPT T RP", [trades, { id: "compare", title: "BEFORE / AFTER", note: null, columns: [c("metric", "METRIC"), c("before", "BEFORE", "num"), c("after", "AFTER", "num")], rows: [{ metric: "VOL", before: 0.2, after: 0.18 }] }],
      [{ label: "METHOD", value: "RISK PARITY" }, { label: "NOTE", value: "ESTIMATED FROM 120 DAYS OF HISTORY, NOT A FORECAST" }]))));
    await run(page, "PORT OPT T METHOD=RP CAP=0.6 LOOKBACK=120");
    await expect(panel(page)).toContainText("NOT A FORECAST");
    await expect(selected(page)).toContainText("SYN0001");
    await expect.poll(() => bodies.opt?.[0]).toEqual({ portfolio: "T", method: "RP", cap: 0.6, lookback: 120 });
    await page.keyboard.press("a");
    await expect.poll(() => puts.length).toBe(1);
    expect(puts[0].url).toBe("/api/portfolios/T.OPT");
    // the original's base and each holding's currency are kept (audit B-1)
    expect(puts[0].body).toEqual({ base: "INR", positions: [
      { symbol: "SYN0001", qty: 80, cost: 101.5, currency: "INR" }, { symbol: "SYN0002", qty: 115, cost: 98.25, currency: null },
    ] });
    await expect(panel(page)).toContainText("SAVED T.OPT");
  });

  test("PORT ATTR: Brinson rows, return measures, and ADD stores a valuation", async ({ page }) => {
    await setup(page);
    await page.route("**/api/portfolios/T/vals", (r) => {
      if (r.request().method() === "PUT") {
        puts.push({ url: "vals", body: r.request().postDataJSON() });
        return r.fulfill({ json: { rows: [] } });
      }
      return r.fulfill({ json: { rows: [{ date: "2024-12-31", value: 9000, flow: 0 }] } });
    });
    await mockQuant(page, "attr", () => job(env(payload("PORT ATTR T", [
      { id: "brinson", title: "BRINSON-FACHLER", note: null, columns: [c("sector", "SECTOR"), c("wp", "WP", "pct"), c("wb", "WB", "pct"), c("allocation", "ALLOC", "pct"), c("selection", "SELECT", "pct"), c("total", "TOTAL", "pct")], rows: [
        { sector: "Technology", wp: 0.7, wb: 0.3, allocation: 0.01, selection: 0.02, total: 0.03 }, { sector: "TOTAL", wp: 1, wb: 1, allocation: 0.01, selection: 0.02, total: 0.03 }] },
      { id: "returns", title: "RETURNS", note: null, columns: [c("measure", "MEASURE"), c("value", "VALUE", "pct")], rows: [{ measure: "TWR", value: 0.32 }] }],
      [{ label: "BASIS", value: "TODAY'S HOLDINGS HELD CONSTANT, NOT YOUR HISTORICAL WEIGHTS" }]))));
    await run(page, "PORT ATTR T BENCH=SPY");
    await expect(panel(page)).toContainText("HELD CONSTANT");
    await expect(selected(page)).toContainText("Technology");
    await page.keyboard.press("v");
    await expect(selected(page)).toContainText("TWR");
    await expect.poll(() => bodies.attr?.[0]).toEqual({ portfolio: "T", bench: "SPY" });
    await run(page, "PORT ATTR T ADD 2025-01-01 VALUE=10000 FLOW=500");
    await expect.poll(() => puts.length).toBe(1);
    expect((puts[0].body as { rows: unknown[] }).rows).toEqual([{ date: "2024-12-31", value: 9000, flow: 0 }, { date: "2025-01-01", value: 10000, flow: 500 }]);
  });

  test("FACT: factor loadings, the data-end label and the symbol go to the job", async ({ page }) => {
    await setup(page);
    await mockQuant(page, "fact", () => job(env(payload("FACT AAPL", [
      { id: "loadings", title: "FACTOR LOADINGS", note: null, columns: [c("factor", "FACTOR"), c("beta", "BETA", "num4"), c("t", "T", "num")], rows: [{ factor: "MKT-RF", beta: 1.1234, t: 21.5 }, { factor: "MOM", beta: -0.0512, t: -1.2 }] }],
      [{ label: "ALPHA (ANN)", value: "2.1%", raw: 0.021 }, { label: "R2", value: "0.62", raw: 0.62 }, { label: "FACTOR DATA ENDS", value: "2026-08-31" }]))));
    await run(page, "FACT AAPL RANGE=3y");
    await expect(panel(page)).toContainText("FACTOR DATA ENDS 2026-08-31");
    await expect(selected(page)).toContainText("MKT-RF");
    await expect(selected(page)).toContainText("1.1234");
    await expect.poll(() => bodies.fact?.[0]).toEqual({ symbol: "AAPL", range: "3y" });
  });

  test("QL: a calculator runs on bars, a missing input is NOT RUNNABLE", async ({ page }) => {
    await setup(page);
    await mockQuant(page, "ql", (b) =>
      (b as { calc: string }).calc === "DSR"
        ? job(env(payload("DSR", [], [], { status: "NOT RUNNABLE: N, T" })))
        : job(env(payload("GARCH AAPL", [{ id: "forecast", title: "FORECAST", note: null, columns: [c("h", "H", "int"), c("vol", "VOL", "pct")], rows: [{ h: 1, vol: 0.011 }] }], [{ label: "PERSISTENCE", value: "0.97", raw: 0.97 }]))),
    );
    await run(page, "QL GARCH AAPL H=5");
    await expect(panel(page)).toContainText("PERSISTENCE 0.97");
    await expect.poll(() => bodies.ql?.[0]).toEqual({ calc: "GARCH", symbols: ["AAPL"], h: 5 });
    await run(page, "QL DSR SR=0.1");
    await expect(panel(page)).toContainText("NOT RUNNABLE: N, T");
    await run(page, "QL NOPE");
    await expect(panel(page)).toContainText("USAGE: QL");
  });

  test("ALPHA: progress while the scan runs, then the zoo table with labels and the decay chart", async ({ page }) => {
    await setup(page);
    let polls = 0;
    await mockQuant(page, "alpha", () => job(null, { state: "running", progress: 0.4, msg: "factor 10/24", kind: "alpha.scan" }));
    await page.route("**/api/jobs/j1", (r) => {
      polls++;
      const done = job(env(payload("ALPHA SYN", [{ id: "zoo", title: "ALPHA ZOO", note: null, columns: [c("id", "FACTOR"), c("family", "FAMILY"), c("ic_mean", "IC", "num4"), c("ir", "IR", "num"), c("label", "LABEL")], rows: [
        { id: "alpha101_001", family: "alpha101", ic_mean: 0.0312, ir: 0.41, label: "alive", info: "Kakushadze Alpha #1. Formula: rank(ts_argmax(x, 5)) | INPUTS CLOSE" }, { id: "qlib158_ROC5", family: "qlib158", ic_mean: -0.025, ir: -0.3, label: "reversed" }] }],
        [{ label: "UNIVERSE", value: "SYNTHETIC DATA, NOT A MARKET" }], { charts: [{ id: "decay", title: "IC DECAY", xlabel: "H", ylabel: "IC", series: [{ name: "alpha101_001", points: [[1, 0.03], [5, 0.01]] }] }] })), { kind: "alpha.scan" });
      return r.fulfill({ json: polls < 2 ? { ...done, state: "running", progress: 0.8, msg: "factor 20/24", result: null } : done });
    });
    await run(page, "ALPHA UNIVERSE=SYN RANGE=1y H=1,5");
    await expect(panel(page)).toContainText("factor 10/24");
    await expect(panel(page)).toContainText("SYNTHETIC DATA, NOT A MARKET");
    await expect(selected(page)).toContainText("alpha101_001");
    await expect(selected(page)).toContainText("alive");
    await expect(async () => {
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("research-flash")).toContainText("alpha101_001: Kakushadze Alpha #1");
    }).toPass();
    await page.keyboard.press("j");
    await expect(selected(page)).toContainText("reversed");
    await expect.poll(() => bodies.alpha?.[0]).toEqual({ universe: "SYN", range: "1y", h: [1, 5] });
  });

  test("CORR REGIME: state, episodes, and the list go to the job", async ({ page }) => {
    await setup(page);
    await mockQuant(page, "regime", () => job(env(payload("CORR REGIME", [{ id: "episodes", title: "EPISODES", note: null, columns: [c("state", "STATE"), c("start", "START", "date"), c("end", "END", "date"), c("bars", "BARS", "int")], rows: [
      { state: "DIFFUSE", start: "2025-01-02", end: "2025-06-30", bars: 120 }, { state: "FUSED", start: "2025-07-01", end: "2026-10-16", bars: 330 }] }],
      [{ label: "STATE", value: "FUSED" }, { label: "EDGE DENSITY", value: "0.71", raw: 0.71 }]))));
    await run(page, "CORR REGIME WL:TECH WIN=60 EDGE=0.5");
    await expect(panel(page)).toContainText("STATE FUSED");
    await expect(selected(page)).toContainText("DIFFUSE");
    await expect.poll(() => bodies.regime?.[0]).toEqual({ list: "WL:TECH", win: 60, edge: 0.5 });
  });

  test("KITE: status panel shows the login state, L opens the login route in a new tab, there is no order key", async ({ page }) => {
    await setup(page);
    await page.route("**/api/kite/status", (r) => r.fulfill({ json: { state: "KITE LOGIN EXPIRED", message: "KITE LOGIN EXPIRED: run KITE LOGIN", user: "DOC001", logged_in_at: "2026-10-17T03:00:00Z" } }));
    await page.route("**/api/kite/login", (r) => r.fulfill({ status: 200, contentType: "text/html", body: "<html><body>KITE LOGIN PAGE (TEST)</body></html>" }));
    await run(page, "KITE");
    await expect(panel(page)).toContainText("KITE LOGIN EXPIRED");
    await expect(panel(page)).toContainText("DOC001");
    const popup = page.waitForEvent("popup");
    await page.keyboard.press("l");
    expect((await popup).url()).toContain("/api/kite/login");
    for (const k of ["b", "s", "o"]) {
      await page.keyboard.press(k); // buy / sell / order keys do not exist: nothing is sent
    }
    await run(page, "KITE BUY");
    await expect(panel(page)).toContainText("USAGE: KITE");
  });
});
