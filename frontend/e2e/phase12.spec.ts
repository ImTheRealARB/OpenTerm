import { readFile } from "node:fs/promises";
import { expect, test, type Download, type Page, type WebSocketRoute } from "@playwright/test";

/*
 * Phase 12 (spec: docs/specs/PHASE_12.md): BT, BT RUNS, IMPORT.
 * Written before the code: each test calls test.fail() until its build step lands; that step deletes the call.
 * Routes and the WebSocket are mocked; `J` frames drive the job.
 */

const now = () => Date.now() / 1000;
let ws: WebSocketRoute | null = null;

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

async function setup(page: Page) {
  ws = null;
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
    if (req.method() === "POST") posts.push({ url: path, body: req.postDataJSON?.() ?? req.postData() });
    if (path === "/api/bt/run") return r.fulfill({ json: { id: "j1", kind: "bt.run", state: "queued", progress: 0, msg: "", cached: false } });
    if (path === "/api/bt/runs") return r.fulfill({ json: { runs: [...runs.values()].map(({ equity, benchmark, trades, ...card }) => card) } });
    const m = /^\/api\/bt\/runs\/(\w+)$/.exec(path);
    if (m) return r.fulfill({ json: runs.get(m[1]) });
    if (path === "/api/bt/compare") return r.fulfill({ json: { a: runs.get("r1"), b: runs.get("r2"), diff: { total_return: -1.8 } } });
    if (path === "/api/bt/import") return r.fulfill({ json: { symbol: "MYBARS", rows: 3, label: "LOCAL DATA" } });
    return r.fulfill({ status: 404, json: { error: "not mocked" } });
  });
  await page.route("**/api/jobs/j1", (r) => r.fulfill({ json: { id: "j1", kind: "bt.run", state: "done", progress: 1, msg: "", cached: false, result: { run_id: "r1" } } }));
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
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
  test.fail();
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

test("BT: Tab cycles CHART / METRICS / TRADES / CODE and E exports the visible table", async ({ page }) => {
  test.fail();
  await setup(page);
  await cmd(page, "BT AAPL SMA20>SMA50 1D 5Y");
  frame("done", 1, "", { run_id: "r1" });
  const p = panel(page);
  await expect(p).toContainText("HISTORICAL SIMULATION");
  await expect(async () => {
    await page.keyboard.press("Tab");
    await expect(p.locator(".bt-view")).toHaveText("METRICS", { timeout: 500 });
  }).toPass();
  await expect(p.locator(".grid .sr")).toContainText("FINAL VALUE");
  await page.keyboard.press("Tab");
  await expect(p.locator(".bt-view")).toHaveText("TRADES");
  const [dl]: [Download, void] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("e")]);
  expect(dl.suggestedFilename()).toMatch(/^BT_.*TRADES.*\.csv$/);
  expect(await readFile((await dl.path())!, "utf-8")).toContain("AAPL");
  await page.keyboard.press("Tab");
  await expect(p.locator(".bt-view")).toHaveText("CODE");
  await expect(p).toContainText("SMA20>SMA50");
});

test("BT: a bad rule shows the parser error at its column and sends nothing", async ({ page }) => {
  test.fail();
  const { posts } = await setup(page);
  await cmd(page, "BT AAPL SMA20>>SMA50 1D 5Y");
  await expect(panel(page)).toContainText("BAD RULE");
  await expect(panel(page)).toContainText("COLUMN 7"); // 1-based for people; the API's col is 0-based (6)
  expect(posts.filter((p) => p.url === "/api/bt/run")).toHaveLength(0);
});

test("BT RUNS: lists run cards and C compares two", async ({ page }) => {
  test.fail();
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

test("IMPORT: paste CSV, preview, Enter stores it as LOCAL DATA", async ({ page }) => {
  test.fail();
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
