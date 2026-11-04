import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/**
 * Part 4: classic-terminal workflow conventions in Terminal mode (openApp default).
 * Sector words, number-select, sector keys, the back key, the FUNC directory and code aliases.
 */
const now = () => Date.now() / 1000;
const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} NAME`, currency: "USD", exchange: "X", tz: "America/New_York", price, prev_close: price * 0.99,
  change: price * 0.01, change_pct: 1.01, open: null, high: price * 1.01, low: price * 0.98, volume: 1000, high_52w: null,
  low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now(),
});
const env = (data: unknown) => ({ data, source: "yahoo", as_of: now(), age_s: 1, stale: false, fallback_from: [] });

const cmd = async (page: Page, text: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const input = (page: Page) => page.locator("#cmdline");

test.beforeEach(async ({ page }) => {
  // Everything else in the app must not reach a real backend; quotes are mocked below.
  await page.route("**/api/**", (r) => r.abort());
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, 100 + i))])) } });
  });
  await openApp(page);
});

test("sector words map to symbols", async ({ page }) => {
  await cmd(page, "SPX INDEX DES");
  await expect(panel(page).locator(".ph")).toContainText("^GSPC | DES");
  await cmd(page, "eurusd curncy des");
  await expect(panel(page).locator(".ph")).toContainText("EURUSD=X | DES");
  await cmd(page, "CL1 COMDTY DES");
  await expect(panel(page).locator(".ph")).toContainText("CL=F | DES");
  await cmd(page, "AAPL US EQUITY DES");
  await expect(panel(page).locator(".ph")).toContainText("AAPL | DES");
  await cmd(page, "US10Y GOVT DES");
  await expect(panel(page).locator(".ph")).toContainText("^TNX | DES");
  await cmd(page, "IBM CORP DES");
  await expect(page.locator(".msg.err")).toContainText("CORP");
});

test("number-select: digits then Enter open that row", async ({ page }) => {
  await cmd(page, "Q AAPL MSFT NVDA");
  await expect(panel(page).locator(".grid .sr")).toContainText("AAPL");
  await page.keyboard.press("Escape"); // leave the command line so keys reach the panel
  await page.keyboard.press("3");
  await expect(page.locator(".msg")).toContainText("ROW 3");
  await page.keyboard.press("Enter");
  await expect(panel(page).locator(".ph")).toContainText("NVDA | DES");

  // A row past the end says so and opens nothing.
  await page.keyboard.press("Alt+Backspace"); // back to the Q list
  await expect(panel(page).locator(".grid .sr")).toContainText("AAPL");
  await page.keyboard.press("Escape");
  await page.keyboard.press("9");
  await page.keyboard.press("Enter");
  await expect(page.locator(".msg")).toContainText("NO ROW 9");
  await expect(panel(page).locator(".ph")).toContainText("Q");
});

test("number-select does not eat '3:' panel targets", async ({ page }) => {
  await cmd(page, "Q AAPL MSFT");
  await expect(panel(page).locator(".grid .sr")).toContainText("AAPL");
  await page.keyboard.press("Escape");
  await page.keyboard.type("1:");
  await expect(input(page)).toHaveValue("1:");
});

test("F-keys write the sector word on the command line", async ({ page }) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type("SPX");
  await page.keyboard.press("F3");
  await expect(input(page)).toHaveValue("SPX INDEX ");
  await page.keyboard.press("F4"); // replaces the old word
  await expect(input(page)).toHaveValue("SPX CURNCY ");
  await page.keyboard.press("F3");
  await page.keyboard.type("DES");
  await page.keyboard.press("Enter");
  await expect(panel(page).locator(".ph")).toContainText("^GSPC | DES");
});

test("Alt+Backspace goes back one panel view", async ({ page }) => {
  await cmd(page, "AAPL DES");
  await cmd(page, "MSFT DES");
  await expect(panel(page).locator(".ph")).toContainText("MSFT | DES");
  await page.keyboard.press("Alt+Backspace");
  await expect(panel(page).locator(".ph")).toContainText("AAPL | DES");
});

test("FUNC lists codes, filters by typing and opens one with Enter", async ({ page }) => {
  await cmd(page, "FUNC");
  await expect(panel(page)).toContainText("FUNCTION DIRECTORY");
  await page.keyboard.press("Escape");
  // Wait until typing really filters (panel keys register after the module loads).
  await expect(async () => {
    await page.keyboard.type("wcrs");
    await expect(panel(page)).toContainText("FILTER: WCRS");
  }).toPass();
  await expect(panel(page).locator(".grid .sr")).toContainText("WCRS");
  await page.keyboard.press("Enter"); // an alias opens the canonical function
  await expect(panel(page).locator(".ph")).toContainText("FXC");
});

test("aliases run the canonical function", async ({ page }) => {
  await cmd(page, "MOST");
  await expect(panel(page).locator(".ph")).toContainText("MOV");
  await cmd(page, "MENU");
  await expect(panel(page)).toContainText("FUNCTION DIRECTORY");
});
