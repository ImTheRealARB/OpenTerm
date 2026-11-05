import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";
import { openApp } from "./app";

// HOME page + ticker tape. Mocked routes only (no network). Headlines and prices below are MADE-UP test data in the shape the
// backend returns; none of it is real.

const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "test feed", as_of: now(), age_s: 5, stale: false, fallback_from: [], ...extra });
const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} NAME`, currency: "USD", exchange: "X", tz: "UTC", price, prev_close: price * 0.99, change: price * 0.01,
  change_pct: 1.01, open: null, high: price * 1.01, low: price * 0.98, volume: 1000, high_52w: null, low_52w: null,
  market_time: Math.floor(now()), source: "yahoo", as_of: now(),
});

let ws: WebSocketRoute | null = null;
const subscribed = new Set<string>();
const quoteCalls: string[][] = [];
const newsCalls: string[] = [];

/** Mocks quotes, the socket and news. Section "india" fails on purpose (an honest ERR block); every other section answers. */
async function mock(page: Page) {
  ws = null;
  subscribed.clear();
  quoteCalls.length = 0;
  newsCalls.length = 0;
  await page.routeWebSocket(/\/ws$/, (route) => {
    ws = route;
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "sub") for (const s of msg[1] as string[]) subscribed.add(s);
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    quoteCalls.push(syms);
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, 100 + i), { source: "yahoo" })])) } });
  });
  await page.route("**/api/news?**", (r) => {
    const u = new URL(r.request().url());
    const section = u.searchParams.get("section") ?? "top";
    newsCalls.push(section);
    if (section === "india") return r.fulfill({ status: 502, json: { error: "ALL NEWS FEEDS DOWN", kind: "unavailable", detail: "rss: timeout" } });
    const items = [0, 1, 2].map((i) => ({
      id: `${section}-${i}`, title: `${section} headline ${i}`, url: `https://example.test/${section}/${i}`, publisher: "Test Wire",
      published: now() - 60 * (i + 1), summary: null, source: "rss",
    }));
    return r.fulfill({ json: env({ kind: "top", query: null, items, failed: [] }) });
  });
  await page.route("**/api/history?**", (r) => r.fulfill({ status: 404, json: { error: "NO HISTORY IN THIS TEST", kind: "not_found" } }));
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const tapeItem = (page: Page, sym: string) => page.locator(`[data-testid="tape"] .tp[data-sym="${sym}"]`).first();

test("a fresh start opens HOME: tape, number blocks and headline blocks with source and age", async ({ page }) => {
  await mock(page);
  await openApp(page, { home: true });
  await expect(page.getByTestId("home")).toBeVisible();
  // the tape: label, last price and change % per item (the strip is drawn twice for the loop, so take the first copy)
  await expect(page.getByTestId("tape")).toBeVisible();
  await expect(tapeItem(page, "^GSPC")).toContainText("SPX");
  await expect(tapeItem(page, "^GSPC")).toContainText("1.01%");
  // number blocks
  await expect(page.getByTestId("home-q-^NSEI")).toContainText("NIFTY 50");
  // headline blocks: one request per section, rows show source, age and title
  await expect(page.getByTestId("home-block-markets")).toContainText("markets headline 0");
  await expect(page.getByTestId("home-block-markets")).toContainText("TEST WIRE");
  await expect(page.getByTestId("home-block-markets")).toContainText("TEST FEED 5S");
  expect(newsCalls).toEqual(expect.arrayContaining(["top", "markets", "economy", "companies", "tech", "india", "commodities", "crypto"]));
  // one block failing says so, with the reason, and invents nothing
  await expect(page.getByTestId("home-block-india")).toContainText("ERR ALL NEWS FEEDS DOWN");
  await expect(page.getByTestId("home-block-india")).not.toContainText("headline");
  // ONE snapshot request and one subscription cover the tape and the blocks together
  expect(quoteCalls.length).toBe(1);
  await expect.poll(() => subscribed.has("^GSPC") && subscribed.has("BTC-USD") && subscribed.has("^VIX")).toBe(true);
});

test("a live tick updates the tape and the block number in place", async ({ page }) => {
  await mock(page);
  await openApp(page, { home: true });
  await expect.poll(() => subscribed.has("^GSPC")).toBe(true);
  await expect(tapeItem(page, "^GSPC")).toContainText("SPX");
  // wire row: [symbol, price, change, pct, volume, high, low, time, src]
  await expect(async () => {
    ws!.send(JSON.stringify(["T", [["^GSPC", 5123.45, 12.3, -0.24, 1000, 5130, 5100, Date.now(), "y"]]]));
    await expect(tapeItem(page, "^GSPC")).toContainText("5,123.45", { timeout: 500 });
  }).toPass({ timeout: 8000 });
  await expect(tapeItem(page, "^GSPC")).toContainText("-0.24%");
  await expect(tapeItem(page, "^GSPC").locator(".down")).toHaveCount(1);
  await expect(page.getByTestId("home-q-^GSPC")).toContainText("5,123.45");
});

test("TAPE ADD / DEL / RESET / ON edit the tape; HOME brings the page back", async ({ page }) => {
  await mock(page);
  await openApp(page, { home: true });
  await expect(tapeItem(page, "^GSPC")).toBeVisible();
  await run(page, "TAPE ADD aapl");
  await expect(tapeItem(page, "AAPL")).toBeVisible();
  await run(page, "TAPE DEL ^GSPC");
  await expect(page.locator('[data-testid="tape"] .tp[data-sym="^GSPC"]')).toHaveCount(0);
  await run(page, "TAPE RESET");
  await expect(tapeItem(page, "^GSPC")).toBeVisible();
  await expect(page.locator('[data-testid="tape"] .tp[data-sym="AAPL"]')).toHaveCount(0);

  // TAPE ON: the tape also sits in the top bar, so HOME drops its own copy (one tape on screen, not two)
  await run(page, "TAPE ON");
  await expect(page.locator(".tape-slot [data-testid=tape]")).toBeVisible();
  await expect(page.getByTestId("tape")).toHaveCount(1);
  await run(page, "TAPE OFF");
  await expect(page.locator(".tape-slot")).toHaveCount(0);

  // leave HOME, then bring it back by name
  await run(page, "Q AAPL");
  await expect(page.getByTestId("home")).toHaveCount(0);
  await run(page, "HOME");
  await expect(page.getByTestId("home")).toBeVisible();
});

test("keys: J/K rows, L next block, Enter opens the article in a new tab", async ({ page }) => {
  await mock(page);
  await openApp(page, { home: true });
  await expect(page.getByTestId("home-block-top")).toContainText("top headline 0");
  // the cursor starts on the first number (S&P 500)
  await expect(page.getByTestId("home-q-^GSPC")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("j");
  await expect(page.getByTestId("home-q-^IXIC")).toHaveAttribute("aria-selected", "true");
  // L hops blocks (indices -> assets -> rates -> top headlines): three hops
  await page.keyboard.press("l");
  await page.keyboard.press("l");
  await page.keyboard.press("l");
  await expect(page.getByTestId("home-block-top").locator('[aria-selected="true"]')).toContainText("top headline 1"); // the row number (second) is kept across blocks
  // The article tab would try the real network: answer it from a mock so the tab's URL is the link we clicked.
  await page.context().route("https://example.test/**", (r) => r.fulfill({ contentType: "text/html", body: "<p>article</p>" }));
  const popup = page.waitForEvent("popup");
  await page.keyboard.press("Enter");
  const tab = await popup;
  await tab.waitForLoadState();
  expect(tab.url()).toBe("https://example.test/top/1");
});

test("the saved layout stays available: startup=layout restores it instead of HOME", async ({ page }) => {
  await mock(page);
  await openApp(page); // default seed: startup=layout, so the start panel is HELP, not HOME
  await expect(page.getByTestId("home")).toHaveCount(0);
});
