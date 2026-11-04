import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/*
 * Step 5 of docs/specs/NEXT_FEATURES.md: the plain-English rule builder in the GUI BT panel.
 * Mocked routes only. The POST /api/bt/run answer is a cached, finished run so no job frames are needed.
 */

const now = () => Date.now() / 1000;
const DAYS = Array.from({ length: 60 }, (_, i) => 1_700_000_000 + i * 86_400);
const RUN = (rule: string) => ({
  id: "r1", rule, strategy: null, symbols: ["AAPL"], interval: "1D", range: "5Y", created_at: now(),
  labels: {
    headline: "HISTORICAL SIMULATION, NOT A FORECAST", prices: "ADJ", engine: "us", fees_bps: 0, slip_bps: 5,
    warmup_bars: 0, sources: [{ name: "yahoo", as_of: now() - 60, age_s: 60 }], data_note: "",
  },
  metrics: { final_value: 132_000, total_return: 0.32, annual_return: 0.06, max_drawdown: -0.21, sharpe: 0.81, sortino: 1.2, calmar: 0.9, win_rate: 0.41, profit_factor: 1.7, trade_count: 29 },
  equity: DAYS.map((t, i) => [t, 100_000 * (1 + (0.32 * i) / 59)]),
  benchmark: DAYS.map((t, i) => [t, 100_000 * (1 + (0.5 * i) / 59)]),
  trades: [],
});

async function setup(page: Page) {
  const posts: { url: string; body: any }[] = [];
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/cmdhistory**", (r) => r.fulfill({ json: { items: [] } }));
  await page.route("**/api/bt/**", (r) => {
    const req = r.request();
    const path = new URL(req.url()).pathname;
    if (req.method() === "POST") posts.push({ url: path, body: req.postDataJSON() });
    if (path === "/api/bt/templates") return r.fulfill({ json: { templates: [] } });
    if (path === "/api/bt/run") {
      const rule = (req.postDataJSON() as { rule: string }).rule;
      return r.fulfill({ json: { id: "j1", kind: "bt.run", state: "done", progress: 1, msg: "", cached: true, run_id: "r1", run: RUN(rule) } });
    }
    return r.fulfill({ status: 404, json: { error: "not mocked" } });
  });
  await openApp(page, { mode: "gui" });
  return { posts };
}

const panel = (page: Page) => page.locator('[data-panel="1"]');
const openBt = async (page: Page) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type("BT");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};

test("GUI: build 'buy when 20-day crosses above 50-day' and run it", async ({ page }) => {
  const { posts } = await setup(page);
  await openBt(page);
  const p = panel(page);
  await expect(p.getByTestId("bt-rule-builder")).toBeVisible();

  // The form starts as 20-day average crosses above 50-day average; set it explicitly the way a person would.
  await p.getByLabel("Condition 1.1 first value: days").fill("20");
  await p.getByLabel("Condition 1.1 second value: days").fill("50");
  await p.getByLabel("Condition 1.1 comparison").selectOption("crosses above");
  await expect(p.getByTestId("bt-rule-text")).toHaveText("Rule: SMA20 CROSS> SMA50");
  await expect(p.getByTestId("bt-rule-live-sentence")).toHaveText(
    "Buy when the 20-day average crosses above the 50-day average; sell when it crosses back below.",
  );

  await p.getByTestId("bt-rule-run").click();
  await expect.poll(() => posts.some((x) => x.url === "/api/bt/run")).toBe(true);
  expect(posts.find((x) => x.url === "/api/bt/run")!.body).toMatchObject({ rule: "SMA20 CROSS> SMA50", symbols: ["AAPL"], interval: "1D", range: "5Y" });

  // The finished run shows the rule back as a sentence under its header.
  await expect(p).toContainText("HISTORICAL SIMULATION, NOT A FORECAST");
  await expect(p.getByTestId("bt-rule-says")).toHaveText(
    "Buy when the 20-day average crosses above the 50-day average; sell when it crosses back below.",
  );
});

test("GUI: add a condition (AND) and an alternative (OR), change a kind, and remove one", async ({ page }) => {
  const { posts } = await setup(page);
  await openBt(page);
  const p = panel(page);
  await expect(p.getByTestId("bt-rule-builder")).toBeVisible();

  await p.getByRole("button", { name: "+ add condition" }).click();
  await p.getByLabel("Condition 1.2 first value", { exact: true }).selectOption("rsi");
  await p.getByLabel("Condition 1.2 comparison").selectOption("is below");
  await p.getByLabel("Condition 1.2 second value", { exact: true }).selectOption("number");
  await p.getByLabel("Condition 1.2 second value: number").fill("70");
  await expect(p.getByTestId("bt-rule-text")).toHaveText("Rule: SMA20 CROSS> SMA50 AND RSI14 < 70");
  await expect(p.getByTestId("bt-rule-live-sentence")).toContainText("and the 14-day RSI is below 70; sell when that stops being true.");

  await p.getByRole("button", { name: "+ add another way to buy" }).click();
  await p.getByLabel("Condition 2.1 first value", { exact: true }).selectOption("price");
  await p.getByLabel("Condition 2.1 comparison").selectOption("is above");
  await expect(p.getByTestId("bt-rule-text")).toContainText("OR CLOSE > SMA50");

  await p.getByRole("button", { name: "Remove condition 2.1" }).click();
  await expect(p.getByTestId("bt-rule-text")).toHaveText("Rule: SMA20 CROSS> SMA50 AND RSI14 < 70");

  await p.getByTestId("bt-rule-run").click();
  await expect.poll(() => posts.some((x) => x.url === "/api/bt/run")).toBe(true);
  expect(posts.find((x) => x.url === "/api/bt/run")!.body.rule).toBe("SMA20 CROSS> SMA50 AND RSI14 < 70");
});

test("GUI: a bad period disables Run and says why; Ctrl+K still works inside a field", async ({ page }) => {
  await setup(page);
  await openBt(page);
  const p = panel(page);
  await expect(p.getByTestId("bt-rule-builder")).toBeVisible();
  await p.getByLabel("Condition 1.1 first value: days").fill("5000");
  await expect(p.getByTestId("bt-rule-error")).toContainText("Periods are whole numbers from 1 to 1000");
  await expect(p.getByTestId("bt-rule-run")).toBeDisabled();
  await p.getByLabel("Condition 1.1 first value: days").focus();
  await page.keyboard.press("Control+k");
  await page.keyboard.type("BT RUNS");
  await expect(page.locator("input:focus")).toHaveValue(/BT RUNS/);
});

test("Terminal: the empty BT panel has no rule builder", async ({ page }) => {
  await page.route("**/api/cmdhistory**", (r) => r.fulfill({ json: { items: [] } }));
  await openApp(page);
  await page.keyboard.press("Control+k");
  await page.keyboard.type("BT");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
  await expect(panel(page)).toContainText("NO BACKTEST OPEN");
  await expect(page.getByTestId("bt-rule-builder")).toHaveCount(0);
});
