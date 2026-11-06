import { readFile } from "node:fs/promises";
import { expect, test, type Download, type Page, type WebSocketRoute } from "@playwright/test";
import { openApp } from "./app";

/*
 * Phase 12 (spec: docs/specs/PHASE_12.md): BT, BT RUNS, IMPORT.
 * Written before the code; every build step has landed and the test.fail() calls are gone.
 * Routes and the WebSocket are mocked; `J` frames drive the job.
 */

const now = () => Date.now() / 1000;
let ws: WebSocketRoute | null = null;

// Strategy editor mocks. `checkReply` is what POST /api/bt/check answers; a test changes it to simulate a sandbox error.
const TEMPLATE_CODE = "import numpy as np\nimport pandas as pd\n\n\nclass SignalEngine:\n    def generate(self, data_map):\n        return {}\n";
const TEMPLATES = [
  { id: "sma_cross", title: "SMA CROSSOVER", summary: "Long when the fast average is above the slow one.", code: TEMPLATE_CODE },
  { id: "rsi_mean_reversion", title: "RSI MEAN REVERSION", summary: "Buy oversold, sell overbought.", code: "# rsi\n" + TEMPLATE_CODE },
  { id: "breakout", title: "CHANNEL BREAKOUT", summary: "Long above the 20-day high.", code: "# breakout\n" + TEMPLATE_CODE },
];
let checkReply: (code: string) => unknown = () => ({ ok: true });
const box = (page: Page) => panel(page).locator('.cm-content[aria-label="strategy code"]');

const DAYS = Array.from({ length: 60 }, (_, i) => 1_700_000_000 + i * 86_400);
const run = (id: string, rule: string, total: number) => ({
  id, rule, strategy: null, symbols: ["AAPL"], interval: "1D", range: "5Y", created_at: now(),
  labels: {
    headline: "HISTORICAL SIMULATION, NOT A FORECAST", prices: "ADJ", engine: "us", fees_bps: 0, slip_bps: 5,
    warmup_bars: 0, sources: [{ name: "yahoo", as_of: now() - 60, age_s: 60 }], data_note: "",
  },
  metrics: { final_value: 100_000 * (1 + total), total_return: total, annual_return: total / 5, max_drawdown: -0.21,
    sharpe: 0.81, sortino: 1.2, calmar: 0.9, win_rate: 0.41, profit_factor: 1.7, trade_count: 29 },
  equity: DAYS.map((t, i) => [t, 100_000 * (1 + (total * i) / 59)]),
  benchmark: DAYS.map((t, i) => [t, 100_000 * (1 + (0.5 * i) / 59)]),
  trades: [
    { symbol: "AAPL", direction: 1, entry_time: "2021-03-01", exit_time: "2021-05-03", entry_price: 120.1,
      exit_price: 131.4, size: 832.6, pnl: 9408.4, commission: 0, exit_reason: "signal" },
    { symbol: "AAPL", direction: 1, entry_time: "2021-06-01", exit_time: "2021-07-01", entry_price: 124.3,
      exit_price: 137.2, size: 875.1, pnl: 11288.8, commission: 0, exit_reason: "signal" },
  ],
});

const MC = {
  run_id: "r1", actual_sharpe: 6.2753, actual_max_dd: -0.2075, p_value_sharpe: 0.041, p_value_max_dd: 0.155,
  simulated_sharpe_mean: 5.01, simulated_sharpe_std: 1.05, simulated_sharpe_p5: 3.66, simulated_sharpe_p95: 6.24,
  n_simulations: 1000, n_trades: 29, sharpe_samples: Array.from({ length: 200 }, (_, i) => 3 + (i % 40) / 10),
  bootstrap: { observed_sharpe: 6.2, ci_lower: 4.1, ci_upper: 8.3, median_sharpe: 6.1, prob_positive: 1, confidence: 0.95, n_bootstrap: 1000 },
  labels: { headline: "HISTORICAL SIMULATION, NOT A FORECAST", engine: "us", validation: "TRADE-ORDER PERMUTATION x1000, BOOTSTRAP x1000 AT 95%, SEED 42" },
};
const WF = {
  run_id: "r1", n_windows: 3, profitable_windows: 2, consistency_rate: 0.6667, return_mean: 0.21, return_std: 0.09,
  sharpe_mean: 1.4, sharpe_std: 0.6,
  windows: [
    { window: 1, start: "2021-01-04", end: "2021-06-30", return: 0.3, sharpe: 1.9, max_dd: -0.08, trades: 4, win_rate: 0.75 },
    { window: 2, start: "2021-07-01", end: "2021-12-31", return: -0.05, sharpe: -0.2, max_dd: -0.12, trades: 3, win_rate: 0.33 },
    { window: 3, start: "2022-01-03", end: "2022-06-30", return: 0.38, sharpe: 2.5, max_dd: -0.05, trades: 5, win_rate: 0.8 },
  ],
  labels: { headline: "HISTORICAL SIMULATION, NOT A FORECAST", engine: "us", validation: "3 EQUAL WINDOWS, NO RE-FITTING" },
};

async function setup(page: Page) {
  ws = null;
  checkReply = () => ({ ok: true });
  const posts: { url: string; body: unknown }[] = [];
  const runs = new Map([["r1", run("r1", "SMA20>SMA50", 3.2)], ["r2", run("r2", "CLOSE>SMA200", 1.4)]]);
  await page.routeWebSocket(/\/ws$/, (route) => {
    ws = route;
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/cmdhistory**", (r) => r.fulfill({ json: { items: [] } }));
  await page.route("**/api/bt/**", (r) => {
    const req = r.request();
    const path = new URL(req.url()).pathname;
    if (req.method() !== "GET") {
      let body: unknown = req.postData();
      try {
        body = req.postDataJSON();
      } catch {
        // a CSV body is plain text
      }
      posts.push({ url: path, body });
    }
    if (path === "/api/bt/templates") return r.fulfill({ json: { templates: TEMPLATES } });
    if (path === "/api/bt/check") return r.fulfill({ json: checkReply((req.postDataJSON() as { code: string }).code) });
    if (path === "/api/bt/run") return r.fulfill({ json: { id: "j1", kind: "bt.run", state: "queued", progress: 0, msg: "", cached: false } });
    if (path === "/api/bt/runs") return r.fulfill({ json: { runs: [...runs.values()].map(({ equity, benchmark, trades, ...card }) => card) } });
    if (path === "/api/bt/strategies") {
      return r.fulfill({ json: { strategies: [{ name: "mysma", kind: "python", updated_at: now() - 90 }, { name: "golden", kind: "rule", updated_at: now() - 30 }] } });
    }
    if (path === "/api/bt/strategies/mysma" && req.method() === "GET") {
      return r.fulfill({ json: { name: "mysma", kind: "python", updated_at: now(), code: "class SignalEngine:\n    def generate(self, data_map):\n        return {}\n" } });
    }
    if (path === "/api/bt/strategies/golden" && req.method() === "GET") return r.fulfill({ json: { name: "golden", kind: "rule", updated_at: now(), code: "SMA20>SMA50" } });
    if (path === "/api/bt/strategies/newone" && req.method() === "GET") return r.fulfill({ status: 404, json: { error: "NO STRATEGY newone", kind: "not_found" } });
    if (path === "/api/bt/strategies/bad" && req.method() === "GET") return r.fulfill({ status: 404, json: { error: "NO STRATEGY bad", kind: "not_found" } });
    if (path === "/api/bt/strategies/bad" && req.method() === "PUT") {
      return r.fulfill({ status: 400, json: { error: "STRATEGY REJECTED", kind: "bad_request", detail: "LINE 2: IMPORT OF os IS NOT ALLOWED" } });
    }
    if (path.startsWith("/api/bt/strategies/")) return r.fulfill({ json: { name: path.split("/").pop(), kind: "python", updated_at: now(), deleted: path.split("/").pop() } });
    if (/\/export$/.test(path)) {
      return r.fulfill({ contentType: "text/plain", body: path.includes("/r1/") ? "//@version=5\nstrategy(\"OpenTerm BT\")\n" : "x" });
    }
    const v = /^\/api\/bt\/runs\/(\w+)\/(mc|wf)$/.exec(path);
    if (v) {
      const kind = v[2] === "mc" ? "bt.mc" : "bt.wf";
      return r.fulfill({ json: { id: `v-${v[2]}`, kind, state: "done", progress: 1, msg: "", cached: false, result: v[2] === "mc" ? MC : WF } });
    }
    const m = /^\/api\/bt\/runs\/(\w+)$/.exec(path);
    if (m) return r.fulfill({ json: runs.get(m[1]) });
    if (path === "/api/bt/compare") return r.fulfill({ json: { a: runs.get("r1"), b: runs.get("r2"), diff: { total_return: -1.8 } } });
    if (path === "/api/bt/import" && req.method() === "GET") {
      return r.fulfill({ json: { symbols: [{ symbol: "MYBARS", rows: 3, first_date: "2024-01-02", last_date: "2024-01-04", created_at: now(), label: "LOCAL DATA" }] } });
    }
    if (path === "/api/bt/import/MYBARS") return r.fulfill({ json: { deleted: "MYBARS" } });
    if (path === "/api/bt/import") return r.fulfill({ json: { symbol: "MYBARS", rows: 3, first_date: "2024-01-02", last_date: "2024-01-04", label: "LOCAL DATA" } });
    return r.fulfill({ status: 404, json: { error: "not mocked" } });
  });
  await page.route("**/api/jobs/j1", (r) => r.fulfill({ json: { id: "j1", kind: "bt.run", state: "done", progress: 1, msg: "", cached: false, result: { run_id: "r1" } } }));
  await openApp(page); // fresh context: localStorage is already empty; openApp seeds terminal mode
  return { posts };
}

const cmd = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const frame = (state: string, progress: number, msg = "", result?: unknown) =>
  ws!.send(JSON.stringify(["J", { id: "j1", kind: "bt.run", state, progress, msg, cached: false, ...(result ? { result } : {}) }]));

test("BT: a rule run shows progress, then the labelled result", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "BT AAPL SMA20>SMA50 1D 5Y");
  await expect.poll(() => posts.some((p) => p.url === "/api/bt/run")).toBe(true);
  expect(posts.find((p) => p.url === "/api/bt/run")!.body).toMatchObject({ rule: "SMA20>SMA50", symbols: ["AAPL"], interval: "1D", range: "5Y" });
  const p = panel(page);
  frame("running", 0.4, "simulating");
  await expect(p).toContainText("40%");
  frame("done", 1, "", { run_id: "r1" });
  await expect(p).toContainText("HISTORICAL SIMULATION, NOT A FORECAST");
  await expect(p).toContainText("ADJ");
  await expect(p).toContainText("SLIP 5 BPS");
  await expect(p).toContainText("YAHOO");
});

test("BT: V cycles CHART / METRICS / TRADES / CODE and E exports the visible table", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT AAPL SMA20>SMA50 1D 5Y");
  frame("done", 1, "", { run_id: "r1" });
  const p = panel(page);
  await expect(p).toContainText("HISTORICAL SIMULATION");
  await expect(async () => {
    await page.keyboard.press("v");
    await expect(p.locator(".bt-view")).toHaveText("METRICS", { timeout: 500 });
  }).toPass();
  await expect(p.locator(".grid .sr")).toContainText("FINAL VALUE");
  await page.keyboard.press("v");
  await expect(p.locator(".bt-view")).toHaveText("TRADES");
  const [dl]: [Download, void] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("e")]);
  expect(dl.suggestedFilename()).toMatch(/^BT_.*TRADES.*\.csv$/);
  expect(await readFile((await dl.path())!, "utf-8")).toContain("AAPL");
  await page.keyboard.press("v");
  await expect(p.locator(".bt-view")).toHaveText("CODE");
  await expect(p).toContainText("SMA20>SMA50");
});

test("BT: a bad rule shows the parser error at its column and sends nothing", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "BT AAPL SMA20>>SMA50 1D 5Y");
  await expect(panel(page)).toContainText("BAD RULE");
  await expect(panel(page)).toContainText("COLUMN 7"); // 1-based for people; the API's col is 0-based (6)
  expect(posts.filter((p) => p.url === "/api/bt/run")).toHaveLength(0);
});

test("BT RUNS: lists run cards and C compares two", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT RUNS");
  const p = panel(page);
  await expect(p.locator(".grid .sr")).toContainText("SMA20>SMA50");
  await expect(async () => {
    await page.keyboard.press("c");
    await expect(p).toContainText("MARKED 1", { timeout: 500 });
  }).toPass();
  await page.keyboard.press("j");
  await page.keyboard.press("c");
  await expect(p).toContainText("COMPARE");
  await expect(p).toContainText("CLOSE>SMA200");
  await expect(p).toContainText("-180.00%"); // the total-return difference
});

test("IMPORT: paste CSV, preview, Ctrl+Enter stores it as LOCAL DATA", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "IMPORT MYBARS");
  const box = panel(page).locator("textarea");
  await expect(box).toBeFocused();
  await box.fill("date,open,high,low,close,volume\n2024-01-02,10,11,9,10.5,100\n2024-01-03,10.5,12,10,11.5,120\n2024-01-04,11.5,12,11,11,90\n");
  await expect(panel(page)).toContainText("3 ROWS");
  await page.keyboard.press("Control+Enter");
  await expect.poll(() => posts.some((p) => p.url === "/api/bt/import")).toBe(true);
  await expect(panel(page)).toContainText("LOCAL DATA");
});

test("BT: M runs a Monte Carlo on the open run and adds a labelled MC view with the histogram", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "BT AAPL SMA20>SMA50 1D 5Y");
  frame("done", 1, "", { run_id: "r1" });
  const p = panel(page);
  await expect(p).toContainText("HISTORICAL SIMULATION");
  await expect(async () => {
    await page.keyboard.press("m");
    await expect(p.locator(".bt-view")).toHaveText("MC", { timeout: 500 });
  }).toPass();
  expect(posts.some((x) => x.url === "/api/bt/runs/r1/mc")).toBe(true);
  await expect(p).toContainText("P-VALUE 4.1%");
  await expect(p).toContainText("BOOTSTRAP SHARPE 95% CI 4.10 TO 8.30");
  await expect(p).toContainText("TRADE-ORDER PERMUTATION x1000");
  await expect(p).toContainText("NOT WHETHER THE RULE HAS AN EDGE");
  await expect(p.getByTestId("mc-hist")).toContainText("ACTUAL");
  await expect(p).toContainText("1-5: CHART METRICS TRADES CODE MC");
  await page.keyboard.press("v"); // wraps around to CHART
  await expect(p.locator(".bt-view")).toHaveText("CHART");
});

test("BT WF: runs the backtest, then the walk-forward windows table", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "BT WF AAPL SMA20>SMA50 1D 5Y");
  await expect.poll(() => posts.some((x) => x.url === "/api/bt/run")).toBe(true);
  frame("done", 1, "", { run_id: "r1" });
  const p = panel(page);
  await expect(p.locator(".bt-view")).toHaveText("WF");
  expect(posts.some((x) => x.url === "/api/bt/runs/r1/wf")).toBe(true);
  await expect(p).toContainText("2 OF 3 WINDOWS PROFITABLE (66.7%)");
  await expect(p.locator(".grid .sr")).toContainText("2021-01-04");
  await page.keyboard.press("j");
  await expect(p.locator(".grid .sr")).toContainText("2021-07-01");
  const [dl]: [Download, void] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("e")]);
  expect(dl.suggestedFilename()).toMatch(/^BT_.*WALKFORWARD.*\.csv$/);
  expect(await readFile((await dl.path())!, "utf-8")).toContain("2022-01-03");
});

test("BT MC: a failed validation job says why and keeps the run on screen", async ({ page }) => {
  await setup(page);
  await page.route("**/api/bt/runs/r1/mc", (r) => r.fulfill({ status: 400, json: { error: "SEED MUST BE AN INTEGER 0-2147483647", kind: "bad_request" } }));
  await cmd(page, "BT AAPL SMA20>SMA50 1D 5Y");
  frame("done", 1, "", { run_id: "r1" });
  const p = panel(page);
  await expect(p).toContainText("HISTORICAL SIMULATION");
  await expect(async () => {
    await page.keyboard.press("m");
    await expect(p).toContainText("ERR: SEED MUST BE AN INTEGER", { timeout: 500 });
  }).toPass();
  await expect(p.locator(".bt-view")).toHaveText("CHART");
});

test("BT OPEN: shows a stored run with its labels", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT OPEN r1");
  await expect(panel(page)).toContainText("HISTORICAL SIMULATION, NOT A FORECAST");
  await expect(panel(page)).toContainText("SMA20>SMA50");
});

test("BT RUNS: Enter opens the selected run in the same panel", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT RUNS");
  const p = panel(page);
  await expect(p.locator(".grid .sr")).toContainText("SMA20>SMA50");
  await expect(async () => {
    await page.keyboard.press("j");
    await page.keyboard.press("Enter");
    await expect(p).toContainText("HISTORICAL SIMULATION", { timeout: 500 });
  }).toPass();
  await expect(p).toContainText("CLOSE>SMA200");
});

test("BT RUNS: V switches the comparison to the two equity lines and Backspace returns to the list", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT RUNS");
  const p = panel(page);
  await expect(p.locator(".grid .sr")).toContainText("SMA20>SMA50");
  await expect(async () => {
    await page.keyboard.press("c");
    await expect(p).toContainText("MARKED 1", { timeout: 500 });
  }).toPass();
  await page.keyboard.press("j");
  await page.keyboard.press("c");
  await expect(p.locator(".bt-view")).toHaveText("METRICS");
  await page.keyboard.press("v");
  await expect(p.locator(".bt-view")).toHaveText("CHART");
  await page.keyboard.press("Backspace");
  await expect(p).toContainText("STORED (LAST 200)");
});

test("BT EXPORT: saves the Pine Script of a rule run", async ({ page }) => {
  await setup(page);
  const [dl]: [Download, void] = await Promise.all([page.waitForEvent("download"), cmd(page, "BT EXPORT r1 PINE")]);
  expect(dl.suggestedFilename()).toBe("BT_r1.pine");
  expect(await readFile((await dl.path())!, "utf-8")).toContain("//@version=5");
  await expect(panel(page)).toContainText("EXPORTED BT_r1.pine");
});

test("BT: P on an open run saves its Pine Script, a bad export command shows the usage", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT AAPL SMA20>SMA50 1D 5Y");
  frame("done", 1, "", { run_id: "r1" });
  await expect(panel(page)).toContainText("HISTORICAL SIMULATION");
  await expect(async () => {
    const [dl]: [Download, void] = await Promise.all([page.waitForEvent("download", { timeout: 600 }), page.keyboard.press("p")]);
    expect(dl.suggestedFilename()).toBe("BT_r1.pine");
  }).toPass();
  await cmd(page, "BT EXPORT");
  await expect(panel(page)).toContainText("USAGE: BT EXPORT <RUNID>");
});

test("IMPORT: a bad CSV lists the problems by row and stores nothing", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "IMPORT BADBARS");
  await panel(page).locator("textarea").fill("date,open,high,low,close\n2024-01-02,1,1,1,1\n2024-13-02,1,1,1,1\n2024-01-04,1,1,2,1\n");
  await expect(panel(page)).toContainText("2 PROBLEMS, NOTHING WILL BE STORED");
  await expect(panel(page)).toContainText("ROW 2: BAD DATE");
  await expect(panel(page)).toContainText("ROW 3: HIGH BELOW LOW");
  await panel(page).locator("textarea").press("Control+Enter");
  expect(posts.filter((x) => x.url === "/api/bt/import")).toHaveLength(0);
});

test("IMPORT: lists stored symbols and D twice removes one", async ({ page }) => {
  const { posts } = await setup(page);
  await page.route("**/api/bt/import/MYBARS", (r) => {
    posts.push({ url: "DELETE /api/bt/import/MYBARS", body: null });
    return r.fulfill({ json: { deleted: "MYBARS" } });
  });
  await cmd(page, "IMPORT");
  const p = panel(page);
  await expect(p.locator(".grid .sr")).toContainText("MYBARS");
  await expect(p).toContainText("LOCAL DATA");
  await expect(async () => {
    await page.keyboard.press("d");
    await expect(p).toContainText("REMOVE MYBARS? PRESS D AGAIN", { timeout: 500 });
  }).toPass();
  await page.keyboard.press("d");
  await expect.poll(() => posts.some((x) => x.url === "DELETE /api/bt/import/MYBARS")).toBe(true);
});

test("BT EDIT: lists saved strategies and Enter opens one in the editor", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT EDIT");
  const p = panel(page);
  await expect(p.locator(".grid .sr")).toContainText("mysma");
  await expect(async () => {
    await page.keyboard.press("Enter");
    await expect(p).toContainText("BT EDIT mysma", { timeout: 500 });
  }).toPass();
  await expect(box(page)).toContainText("class SignalEngine");
  await expect(p).toContainText("SAVED PYTHON STRATEGY");
  // CodeMirror draws line numbers in a gutter next to the text
  await expect(p.locator(".cm-lineNumbers")).toBeVisible();
});

test("BT EDIT: a new name shows the three templates; Enter loads one, Tab indents, Ctrl+S saves it", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "BT EDIT newone");
  const p = panel(page);
  await expect(p).toContainText("NEW PYTHON STRATEGY");
  await expect(p.locator(".grid .sr")).toContainText("SMA CROSSOVER");
  // move down once: the chooser is keyboard driven like every other list
  await expect(async () => {
    await page.keyboard.press("j");
    await expect(p.locator(".grid .sr")).toContainText("RSI MEAN REVERSION", { timeout: 500 });
  }).toPass();
  await page.keyboard.press("Enter");
  await expect(box(page)).toContainText("# rsi");
  await expect(box(page)).toContainText("class SignalEngine");
  await expect(p.locator(".cm-lineNumbers")).toBeVisible();
  await expect(box(page)).toBeFocused();
  await page.keyboard.press("Control+Home");
  await page.keyboard.press("Tab");
  // the first line now starts with four spaces (textContent keeps them; toHaveText would collapse them)
  expect(await p.locator(".cm-line").first().evaluate((el) => el.textContent)).toBe("    # rsi");
  await expect(p).toContainText("UNSAVED CHANGES");
  await page.keyboard.press("Control+s");
  await expect(p).toContainText("SAVED newone (PYTHON)");
  const put = posts.find((x) => x.url === "/api/bt/strategies/newone");
  expect((put!.body as { code: string }).code).toContain("class SignalEngine");
  // Ctrl+S in the editor must not ALSO trigger the global "save workspace" shortcut (which prefills the command line)
  await expect(page.locator("#cmdline")).not.toHaveValue(/LAYOUT SAVE/);
});

test("BT EDIT: T reopens the templates; unsaved changes need a second T", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT EDIT mysma");
  const p = panel(page);
  await expect(box(page)).toContainText("class SignalEngine");
  await box(page).click();
  await page.keyboard.type("# edit");
  await expect(p).toContainText("UNSAVED CHANGES");
  await page.keyboard.press("Escape");
  await expect(async () => {
    await page.keyboard.press("t");
    await expect(p).toContainText("UNSAVED CHANGES: PRESS T AGAIN TO REPLACE", { timeout: 500 });
  }).toPass();
  await page.keyboard.press("t");
  await expect(p.locator(".grid .sr")).toContainText("SMA CROSSOVER");
  await page.keyboard.press("Enter");
  await expect(box(page)).toContainText("class SignalEngine");
  await expect(box(page)).not.toContainText("# edit");
});

test("BT EDIT: the editor's delayed focus retry does not pull focus back after Esc", async ({ page }) => {
  // The box focuses itself when it loads and once more ~80 ms later (the command line takes focus back after
  // Enter). On a busy machine that retry fired after the user had already pressed Esc, so the next T was
  // typed into the code instead of opening the templates. A paused clock makes the order certain.
  await page.clock.install();
  await setup(page);
  // Pause a little in the future: a target that has already passed (busy machine) makes pauseAt throw.
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 2000));
  await cmd(page, "BT EDIT mysma");
  const p = panel(page);
  await expect(box(page)).toContainText("class SignalEngine");
  await box(page).click();
  await page.keyboard.press("Escape");
  await page.clock.runFor(500); // the retry timer fires now, after Esc
  await page.keyboard.press("t");
  await page.clock.runFor(100);
  await expect(p.locator(".grid .sr")).toContainText("SMA CROSSOVER");
  await expect(box(page)).not.toContainText("class SignalEnginet");
});

test("BT EDIT: the server's reason for refusing code is shown on its line and nothing runs", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "BT EDIT bad");
  await expect(panel(page).locator(".grid .sr")).toContainText("SMA CROSSOVER");
  await page.keyboard.press("Enter");
  await expect(box(page)).toContainText("class SignalEngine");
  // The editor's keys can register a moment after its text appears (CLAUDE.md gotcha; lost once on a loaded CI runner):
  // retry Ctrl+Enter until the refusal shows. A repeat is harmless, the save is refused every time.
  await expect(async () => {
    await page.keyboard.press("Control+Enter");
    await expect(panel(page)).toContainText("NOT SAVED: STRATEGY REJECTED: LINE 2: IMPORT OF os IS NOT ALLOWED", { timeout: 1000 });
  }).toPass({ timeout: 8000 });
  // the same reason, drawn inline under line 2 and in the DOM line under the editor
  await expect(panel(page).locator(".cm-sbx-msg")).toHaveText("IMPORT OF os IS NOT ALLOWED");
  await expect(panel(page).locator(".cm-sbx-errline")).toHaveCount(1);
  await expect(panel(page)).toContainText("SANDBOX: LINE 2: IMPORT OF os IS NOT ALLOWED");
  expect(posts.filter((x) => x.url === "/api/bt/run")).toHaveLength(0);
});

test("BT EDIT: the live check marks the offending line 400 ms after typing and clears when fixed", async ({ page }) => {
  const { posts } = await setup(page);
  checkReply = (code) => (code.includes("import os") ? { ok: false, error: "LINE 2: IMPORT os IS NOT ALLOWED (allowed: numpy pandas)" } : { ok: true });
  await cmd(page, "BT EDIT mysma");
  const p = panel(page);
  await expect(box(page)).toContainText("class SignalEngine");
  await expect(p.locator(".cm-sbx-msg")).toHaveCount(0);
  await box(page).click();
  await page.keyboard.press("Control+Home");
  await page.keyboard.type("import os\n");
  await expect(p.locator(".cm-sbx-msg")).toHaveText("IMPORT os IS NOT ALLOWED (allowed: numpy pandas)");
  await expect(p.locator(".cm-sbx-errline")).toHaveCount(1);
  await expect(p).toContainText("SANDBOX: LINE 2: IMPORT os IS NOT ALLOWED");
  expect(posts.some((x) => x.url === "/api/bt/check")).toBe(true);
  // select the first line (Shift+Down) and delete it: the next check answers ok and both displays go
  await page.keyboard.press("Control+Home");
  await page.keyboard.press("Shift+ArrowDown");
  await page.keyboard.press("Backspace");
  await expect(p.locator(".cm-sbx-msg")).toHaveCount(0);
  await expect(p).not.toContainText("SANDBOX:");
});

test("BT EDIT: Ctrl+K pressed inside the editor still opens the command line", async ({ page }) => {
  await setup(page);
  await cmd(page, "BT EDIT mysma");
  await expect(box(page)).toContainText("class SignalEngine");
  await box(page).click();
  await expect(box(page)).toBeFocused();
  await page.keyboard.press("Control+k");
  await expect(page.locator("#cmdline")).toBeFocused();
  // and the editor kept its text: Ctrl+K did not delete a line (macOS binds it to "delete to line end" in CodeMirror)
  await expect(box(page)).toContainText("class SignalEngine");
});

test("BT EDIT: Ctrl+Enter saves and runs the strategy with the RUN line", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "BT EDIT mysma");
  await expect(box(page)).toContainText("class SignalEngine");
  await panel(page).getByLabel("run line").fill("SPY,QQQ 1W 10Y SHORT");
  await panel(page).getByLabel("run line").press("Control+Enter");
  await expect.poll(() => posts.some((x) => x.url === "/api/bt/run")).toBe(true);
  expect(posts.find((x) => x.url === "/api/bt/run")!.body).toMatchObject({ strategy: "mysma", symbols: ["SPY", "QQQ"], interval: "1W", range: "10Y", options: { short: true } });
  expect((posts.find((x) => x.url === "/api/bt/run")!.body as { rule?: string }).rule).toBeUndefined();
  expect(posts.some((x) => x.url === "/api/bt/strategies/mysma")).toBe(true);
});

test("BT: @name runs a saved strategy, BT SAVE stores a rule, BT DEL removes a strategy", async ({ page }) => {
  const { posts } = await setup(page);
  await cmd(page, "BT AAPL @golden 1D 5Y");
  await expect.poll(() => posts.some((x) => x.url === "/api/bt/run")).toBe(true);
  expect(posts.find((x) => x.url === "/api/bt/run")!.body).toMatchObject({ strategy: "golden", symbols: ["AAPL"] });
  await cmd(page, "BT SAVE fast EMA12 CROSS> EMA26");
  await expect(panel(page)).toContainText("SAVED RULE fast: EMA12 CROSS> EMA26");
  expect(posts.find((x) => x.url === "/api/bt/strategies/fast")!.body).toEqual({ rule: "EMA12 CROSS> EMA26" });
  await cmd(page, "BT SAVE broken SMA20>>SMA50");
  await expect(panel(page)).toContainText("BAD RULE");
  await cmd(page, "BT DEL fast");
  await expect(panel(page)).toContainText("DELETED STRATEGY fast");
  await cmd(page, "BT SAVE onlyname");
  await expect(panel(page)).toContainText("USAGE: BT SAVE <NAME> <RULE>");
});
