import { expect, test, type Page } from "@playwright/test";
import { dateOf, env, exportCsv, gauge, now, N, panel, run, setup, T } from "./p19util";

// Phase 19 end-to-end tests (mocked routes only). Steps 1-2: GP studies, patterns, SEAS, drawings, event markers, panes.

test("SEAS: month table, V cycles the view, CSV export", async ({ page }) => {
  await setup(page);
  await run(page, "AAA SEAS");
  const p = panel(page);
  await expect(p).toContainText("SEAS AAA · MONTH");
  await expect(p).toContainText("PAST AVERAGES, NOT A FORECAST");
  await expect(p.locator("tbody tr")).toHaveCount(12);
  await expect(p.locator(".sr")).toContainText("JAN N");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("FEB N");
  await page.keyboard.press("v");
  await expect(p).toContainText("WEEKDAY");
  await expect(p.locator("tbody tr")).toHaveCount(5);
  await page.keyboard.press("v");
  await expect(p.locator("tbody tr")).toHaveCount(31);
  const csv = await exportCsv(page);
  expect(csv.name).toMatch(/^SEAS_AAA_DOM.*\.csv$/);
  expect(csv.text.trim().split(/\r?\n/)[0]).toBe("bucket,n,avg_pct,median_pct,hit_pct,min_pct,max_pct");
});

test("GP: Phase 19 studies and pattern overlays draw without errors", async ({ page }) => {
  const { errors } = await setup(page);
  await run(page, "AAA GP 1Y ATR STOCH KELT DONCH");
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(1 + 2 + 3 + 3);
  await run(page, "AAA GP 1Y PAT:CANDLE PAT:SMC ICHIMOKU SUPERTREND PSAR ADX");
  await expect.poll(() => gauge(page, "chart.markers")).toBeGreaterThan(0);
  expect(await gauge(page, "chart.extraSeries")).toBeGreaterThan(8);
  expect(errors).toEqual([]);
});

test("PERF CALC: chart maths gauges are published (budgets are gated by scripts/bench.mjs)", async ({ page }) => {
  await setup(page);
  await run(page, "PERF CALC");
  await expect(panel(page)).toContainText("TEST DATA, NOT A SECURITY");
  // Sanity only: the 40 / 15 / 1 ms budgets are gated in the bench, not under the parallel gate load.
  await expect.poll(() => gauge(page, "p19.patternsMs")).toBeLessThan(1000);
  await expect.poll(() => gauge(page, "p19.seasMs")).toBeLessThan(1000);
  await expect.poll(() => gauge(page, "p19.hitMs")).toBeLessThan(100);
});

// --- step 2: GP drawings, event markers, panes ---
async function setupStore(page: Page) {
  const base = await setup(page);
  const store: { drawings: unknown[] } = { drawings: [] };
  const puts: unknown[][] = [];
  await page.route("**/api/drawings/**", (r) => {
    if (r.request().method() === "PUT") {
      const body = r.request().postDataJSON() as { drawings: unknown[] };
      store.drawings = body.drawings;
      puts.push(body.drawings);
      return r.fulfill({ json: { symbol: "AAA", drawings: body.drawings, updated_at: now() } });
    }
    return r.fulfill({ json: { symbol: "AAA", drawings: store.drawings, updated_at: store.drawings.length ? now() : null } });
  });
  return { ...base, store, puts };
}

const gpReady = async (page: Page) => {
  await expect(panel(page)).toContainText("T/H/B DRAW");
  await expect.poll(() => gauge(page, "chart.drawSegs")).toBeDefined();
};

test("GP drawings: trend line, horizontal line and fib by keyboard are saved and come back after a reload", async ({ page }) => {
  const { errors, puts } = await setupStore(page);
  await run(page, "AAA GP 1Y");
  await gpReady(page);
  await page.keyboard.press("t");
  await expect(panel(page)).toContainText("DRAW TREND LINE: ANCHOR 1/2 AT CLOSE");
  for (let i = 0; i < 20; i++) await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter");
  await expect(panel(page)).toContainText("ANCHOR 2/2");
  for (let i = 0; i < 20; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("p");
  await expect(panel(page)).toContainText("AT HIGH");
  await page.keyboard.press("Enter");
  await expect(panel(page)).toContainText("TREND LINE d1 SELECTED");
  await page.keyboard.press("h");
  await page.keyboard.press("Enter");
  await expect(panel(page)).toContainText("HORIZONTAL LINE d2 SELECTED");
  await page.keyboard.press("b");
  for (let i = 0; i < 30; i++) await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter");
  for (let i = 0; i < 30; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(panel(page)).toContainText("FIB RETRACEMENT d3 SELECTED");
  await expect.poll(() => gauge(page, "chart.drawSegs")).toBeGreaterThanOrEqual(1 + 1 + 8);
  await expect.poll(() => puts.length).toBeGreaterThan(0);
  await expect.poll(() => (puts[puts.length - 1] as unknown[]).length).toBe(3);
  const saved = puts[puts.length - 1] as { id: string; kind: string; pts: { t: number; p: number }[] }[];
  expect(saved.map((d) => d.kind)).toEqual(["TREND", "HLINE", "FIB"]);
  expect(saved[0].pts).toHaveLength(2);
  expect(saved[0].pts[1].t).toBeGreaterThan(saved[0].pts[0].t);

  // Cycle and delete from the keyboard.
  await page.keyboard.press("]");
  await expect(panel(page)).toContainText("TREND LINE d1 SELECTED");
  await page.keyboard.press("d");
  await expect.poll(() => (puts[puts.length - 1] as unknown[]).length).toBe(2);

  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  await run(page, "AAA GP 1Y");
  await gpReady(page);
  await expect.poll(() => gauge(page, "chart.drawSegs")).toBeGreaterThanOrEqual(1 + 8);
  expect(errors).toEqual([]);
});

test("GP drawings: Escape cancels a placement and nothing is saved", async ({ page }) => {
  const { puts } = await setupStore(page);
  await run(page, "AAA GP 1Y");
  await gpReady(page);
  await page.keyboard.press("t");
  await expect(panel(page)).toContainText("DRAW TREND LINE");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
  await expect(panel(page)).not.toContainText("DRAW TREND LINE");
  await page.waitForTimeout(600);
  expect(puts).toHaveLength(0);
  expect(await gauge(page, "chart.drawSegs")).toBe(0);
});

test("GP EVT: earnings, dividend and split markers land on their bars; a date with no bar is skipped", async ({ page }) => {
  await setupStore(page);
  const d = (i: number) => dateOf(T[N - 1 - i]);
  await page.route("**/api/world/events?**", (r) =>
    r.fulfill({
      json: env(
        {
          symbol: "AAA",
          events: [
            { date: d(40), kind: "E", detail: "EPS 1.91 VS 1.88 (+1.6%)" },
            { date: d(20), kind: "D", detail: "DIV $0.27" },
            { date: d(5), kind: "S", detail: "SPLIT 4:1" },
            { date: "2099-01-01", kind: "E", detail: "EPS FUTURE" },
          ],
          missing: ["SPLITS"],
          notes: ["EARNINGS MARKERS: LAST FOUR REPORTED QUARTERS ONLY (NASDAQ)"],
          source: "nasdaq_research + yahoo",
        },
        { source: "nasdaq_research + yahoo" },
      ),
    }),
  );
  await run(page, "AAA GP 1Y EVT");
  await expect(panel(page)).toContainText("EVT E=EARNINGS (LAST 4 REPORTED)");
  await expect(panel(page)).toContainText("3 IN VIEW OF 4");
  await expect(panel(page)).toContainText("MISSING SPLITS");
  await expect.poll(() => gauge(page, "chart.events")).toBe(3);
});

test("GP PANE: each VS symbol gets its own pane; without PANE only the first is overlaid", async ({ page }) => {
  await setupStore(page);
  await run(page, "AAA GP 1Y VS BBB CCC PANE");
  await expect(panel(page)).toContainText("VS BBB CCC (PANES)");
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(2);
  await run(page, "AAA GP 1Y VS BBB CCC");
  await expect(panel(page)).toContainText("VS OVERLAYS ONLY BBB; ADD PANE TO SHOW ALL 2");
});
