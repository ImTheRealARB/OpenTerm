import { readFile } from "node:fs/promises";
import type { Download, Page } from "@playwright/test";
import { openApp } from "./app";

// Shared by the Phase 19 specs. Mocked routes only (no network). Series are synthetic test data made up here.
export const now = () => Date.now() / 1000;
export const env = (data: unknown, extra = {}) => ({ data, source: "yahoo", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
export const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} NAME`, currency: "USD", exchange: "X", tz: "UTC", price, prev_close: price * 0.99,
  change: price * 0.01, change_pct: 1.01, open: null, high: price * 1.01, low: price * 0.98, volume: 1000, high_52w: null,
  low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now(),
});

export const N = 900;
export const T0 = Math.floor(now() / 86400) * 86400 - (N - 1) * 86400;
export const T = Array.from({ length: N }, (_, i) => T0 + i * 86400);
export const base = (i: number) => 100 + 10 * Math.sin(i / 7) + i * 0.05;
export const dateOf = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);
export const bars = (symbol: string, range: string, interval: string) => {
  const c = T.map((_, i) => base(i));
  return {
    symbol, range, interval, currency: "USD", exchange: "X", tz: "UTC", t: T, o: c.map((x, i) => x + (i % 3) * 0.2), h: c.map((x) => x + 1), l: c.map((x) => x - 1), c,
    v: c.map((_, i) => 1_000_000 + i), adj: c, source: "yahoo", as_of: now(),
  };
};

export async function setup(page: Page) {
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

export const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
export const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
export const gauge = (page: Page, k: string) => page.evaluate((key) => window.__openterm_perf.snapshot().gauges[key], k);

export async function exportCsv(page: Page): Promise<{ name: string; text: string }> {
  const [dl]: [Download, void] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("e")]);
  return { name: dl.suggestedFilename(), text: (await readFile((await dl.path())!, "utf-8")).replace(/^﻿/, "") };
}
