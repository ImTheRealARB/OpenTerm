import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

// Section tiles (components/Tile.tsx): DES and HOME. Mocked routes only. Numbers are MADE-UP test data in the backend's shape.

const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "test feed", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} NAME`, currency: "USD", exchange: "X", tz: "UTC", price, prev_close: price - 1, change: 1, change_pct: 1,
  open: null, high: price + 1, low: price - 2, volume: 1000, high_52w: price + 50, low_52w: price - 50, market_time: Math.floor(now()),
  source: "yahoo", as_of: now(),
});

async function setup(page: Page, opts: { home?: boolean } = {}) {
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, 100 + i), { source: "yahoo" })])) } });
  });
  await page.route("**/api/profile?**", (r) =>
    r.fulfill({ json: env({ symbol: "AAPL", name: "Apple Inc.", sector: "Technology", industry: "Consumer Electronics", description: "Makes phones.", market_cap: 5e12, pe: 39.4, delay_min: 0, source: "yahoo" }) }),
  );
  await page.route("**/api/news?**", (r) => r.fulfill({ json: env({ kind: "top", query: null, items: [], failed: [] }) }));
  await page.route("**/api/history?**", (r) => {
    const t = Array.from({ length: 60 }, (_, i) => 1_790_000_000 + i * 86400);
    const c = t.map((_, i) => 100 + Math.sin(i / 4) * 5);
    return r.fulfill({ json: env({ symbol: "AAPL", range: "1y", interval: "1d", currency: "USD", exchange: "X", tz: "UTC", t, o: c, h: c.map((x) => x + 1), l: c.map((x) => x - 1), c, v: c.map(() => 1000), source: "yahoo", as_of: 0 }) });
  });
  await openApp(page, opts);
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape"); // the command line keeps focus after a run: hand the keys back to the panel
};

test("DES is three tiles; the Price tile's GP > link opens the chart from the keyboard", async ({ page }) => {
  await setup(page);
  await run(page, "AAPL DES");
  const p = page.locator('[data-panel="1"]');
  await expect(p.getByTestId("des-tile-price")).toBeVisible();
  await expect(p.getByTestId("des-tile-figures")).toBeVisible();
  await expect(p.getByTestId("des-tile-company")).toBeVisible();
  // The header strip shows the title and the drill link.
  const go = p.getByTestId("des-tile-price-go");
  await expect(go).toHaveText("GP >");
  await expect(p.getByTestId("des-tile-figures-go")).toHaveText("EE >");
  // Tab moves between the links (a key typed while a link has focus is not taken by the global "next panel" Tab), Enter runs it.
  await p.getByTestId("des-tile-figures-go").focus();
  await page.keyboard.press("Shift+Tab");
  await expect(go).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("AAPL | GP");
  await expect(p.locator(".chart canvas").first()).toBeVisible();
});

test("DES: the drill link also works with a click", async ({ page }) => {
  await setup(page);
  await run(page, "AAPL DES");
  await page.locator('[data-panel="1"]').getByTestId("des-tile-figures-go").click();
  await expect(page.locator('[data-panel="1"] .ph')).toContainText("AAPL | EE");
});

test("HOME: every block is a tile, and a block's drill link opens its function", async ({ page }) => {
  await setup(page, { home: true });
  const home = page.getByTestId("home");
  await expect(home).toBeVisible();
  expect(await home.locator(".tile").count()).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("home-block-indices")).toContainText("INDICES");
  await expect(page.getByTestId("home-block-indices-go")).toHaveText("WEI >");
  await page.getByTestId("home-block-indices-go").click();
  await expect(page.locator(".ph").first()).toContainText("WEI");
});
