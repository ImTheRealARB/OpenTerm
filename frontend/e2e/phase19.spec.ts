import { readFile } from "node:fs/promises";
import { expect, test, type Download, type Page } from "@playwright/test";
import { openApp } from "./app";

// Mocked routes only (no network). Series are synthetic test data made up in this file.
const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "yahoo", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} NAME`, currency: "USD", exchange: "X", tz: "UTC", price, prev_close: price * 0.99,
  change: price * 0.01, change_pct: 1.01, open: null, high: price * 1.01, low: price * 0.98, volume: 1000, high_52w: null,
  low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now(),
});

const N = 900;
const T0 = Math.floor(now() / 86400) * 86400 - (N - 1) * 86400;
const T = Array.from({ length: N }, (_, i) => T0 + i * 86400);
const base = (i: number) => 100 + 10 * Math.sin(i / 7) + i * 0.05;
const bars = (symbol: string, range: string, interval: string) => {
  const c = T.map((_, i) => base(i));
  return {
    symbol, range, interval, currency: "USD", exchange: "X", tz: "UTC", t: T, o: c.map((x, i) => x + (i % 3) * 0.2), h: c.map((x) => x + 1), l: c.map((x) => x - 1), c,
    v: c.map((_, i) => 1_000_000 + i), adj: c, source: "yahoo", as_of: now(),
  };
};

async function setup(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, 100 + i))])) } });
  });
  await page.route("**/api/history?**", (r) => {
    const u = new URL(r.request().url());
    return r.fulfill({ json: env(bars(u.searchParams.get("symbol")!, u.searchParams.get("range") ?? "", u.searchParams.get("interval") ?? "")) });
  });
  await openApp(page);
  return { errors };
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const gauge = (page: Page, k: string) => page.evaluate((key) => window.__openterm_perf.snapshot().gauges[key], k);

async function exportCsv(page: Page): Promise<{ name: string; text: string }> {
  const [dl]: [Download, void] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("e")]);
  return { name: dl.suggestedFilename(), text: (await readFile((await dl.path())!, "utf-8")).replace(/^﻿/, "") };
}

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

test("PERF CALC: chart maths gauges are published and published (budgets are gated by scripts/bench.mjs)", async ({ page }) => {
  await setup(page);
  await run(page, "PERF CALC");
  await expect(panel(page)).toContainText("TEST DATA, NOT A SECURITY");
  await expect.poll(() => gauge(page, "p19.patternsMs")).toBeLessThan(1000); // sanity only: the 40 ms budget is gated in the bench, not under the parallel gate load
  await expect.poll(() => gauge(page, "p19.seasMs")).toBeLessThan(1000);
});
