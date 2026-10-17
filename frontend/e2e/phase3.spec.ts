import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";

const env = (data: unknown, extra = {}) => ({ data, source: "yahoo", as_of: Date.now() / 1000, age_s: 1, stale: false, fallback_from: [], ...extra });
const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} Inc.`, currency: "USD", exchange: "NasdaqGS", tz: "America/New_York", price, prev_close: price - 1,
  change: 1, change_pct: 1, open: null, high: price + 1, low: price - 2, volume: 1000, high_52w: price + 50, low_52w: price - 50,
  market_time: Math.floor(Date.now() / 1000), source: "yahoo", as_of: Date.now() / 1000,
});

let ws: WebSocketRoute | null = null;
const subs: string[][] = [];

async function setup(page: Page) {
  ws = null;
  subs.length = 0;
  await page.routeWebSocket(/\/ws$/, (route) => {
    ws = route;
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "sub") subs.push(msg[1]);
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, 100 + i))])) } });
  });
  await page.route("**/api/profile?**", (r) =>
    r.fulfill({ json: env({ symbol: "AAPL", name: "Apple Inc.", sector: "Technology", industry: "Consumer Electronics", description: "Makes phones.", market_cap: 5e12, pe: 39.4, delay_min: 0, source: "yahoo" }) }),
  );
  await page.route("**/api/history?**", (r) => {
    const n = 60;
    const t = Array.from({ length: n }, (_, i) => 1_790_000_000 + i * 86400);
    const c = t.map((_, i) => 100 + Math.sin(i / 4) * 5);
    return r.fulfill({ json: env({ symbol: "AAPL", range: "1y", interval: "1d", currency: "USD", exchange: "NasdaqGS", tz: "America/New_York", t, o: c, h: c.map((x) => x + 1), l: c.map((x) => x - 1), c, v: c.map(() => 1000), source: "yahoo", as_of: 0 }) });
  });
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
};
const panel = (page: Page, id: number) => page.locator(`[data-panel="${id}"]`);

test("Q: canvas grid, subscribes once, keyboard drill-down and delete", async ({ page }) => {
  await setup(page);
  await run(page, "Q AAPL MSFT NVDA");
  await expect(panel(page, 1).locator("canvas")).toBeVisible();
  await expect(panel(page, 1)).toContainText("3 SECURITIES");
  await expect.poll(() => subs.flat().sort().join(",")).toBe("AAPL,MSFT,NVDA");
  await page.keyboard.press("Escape");
  await page.keyboard.press("j");
  await page.keyboard.press("d"); // delete MSFT
  await expect(panel(page, 1)).toContainText("2 SECURITIES");
  await page.keyboard.press("j");
  await page.keyboard.press("Enter"); // drill into NVDA
  await expect(panel(page, 1).locator(".ph")).toContainText("NVDA | DES");
});

test("DES: profile, and the price line follows streamed ticks", async ({ page }) => {
  await setup(page);
  await run(page, "AAPL DES");
  const p = panel(page, 1);
  await expect(p).toContainText("Apple Inc.");
  await expect(p).toContainText("Technology");
  await expect(p).toContainText("5.00T");
  await expect(p.locator(".big")).toHaveText("100.00");
  await expect.poll(() => subs.flat()).toContain("AAPL");
  ws!.send(JSON.stringify(["T", [["AAPL", 123.45, 24.45, 24.7, 2000, 124, 99, Date.now(), "y"]]]));
  await expect(p.locator(".big")).toHaveText("123.45");
  await expect(p).toContainText("LIVE STREAM");
});

test("GP: chart renders, number keys change range in place", async ({ page }) => {
  await setup(page);
  const ranges: string[] = [];
  page.on("request", (r) => r.url().includes("/api/history") && ranges.push(new URL(r.url()).searchParams.get("range") ?? ""));
  await run(page, "AAPL GP");
  const p = panel(page, 1);
  await expect(p.locator(".chart canvas").first()).toBeVisible();
  await expect(p).toContainText("1Y");
  await page.keyboard.press("Escape");
  await page.keyboard.press("2");
  await expect(p.locator(".line").first()).toContainText("AAPL 5D");
  expect(ranges).toContain("5D");
  await page.keyboard.press("i");
  await expect(p.locator(".picker")).toContainText("RSI");
  await page.keyboard.press("5");
  await page.keyboard.press("Escape");
  await expect(p.locator(".picker")).toHaveCount(0);
  await expect(p.locator(".line").first()).toContainText("RSI");
});
