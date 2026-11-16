import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/**
 * UI parity pass, items 5 and 6 (written by a builder that could not run Playwright: run it once before trusting it).
 *  - Row-number gutter on Q / WL / WEI / FX / CMDTY: on in Terminal by default, off in GUI, switchable with SETTINGS ROWNUMBERS.
 *    The canvas is invisible to the DOM, so the grid publishes `data-gutter` (characters used, 0 = off) and `data-cols` (header words).
 *    Typing a number then Enter is the app-wide number-select (terminal-conventions.spec.ts covers it); one case here proves it still
 *    works with the gutter on.
 *  - Board micro-graphics: WEI has a 2DAY column, and its lines come from ONE batched /api/sparks request.
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
const panel = (page: Page) => page.locator('[data-panel="1"]');
const grid = (page: Page) => panel(page).locator(".grid");

let sparkCalls: string[][] = [];

test.beforeEach(async ({ page }) => {
  sparkCalls = [];
  await page.route("**/api/**", (r) => r.abort());
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, 100 + i))])) } });
  });
  await page.route("**/api/sparks?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    sparkCalls.push(syms);
    // A rising two-session line for every symbol except the first (that one gets no points: its cell must stay blank).
    return r.fulfill({ json: env(Object.fromEntries(syms.slice(1).map((s) => [s, [98, 99, 98.5, 100, 101]]))) });
  });
});

test("Terminal: the gutter is on by default and SETTINGS ROWNUMBERS OFF removes it", async ({ page }) => {
  await openApp(page);
  await cmd(page, "Q AAPL MSFT NVDA");
  await expect(grid(page).locator(".sr")).toContainText("AAPL");
  await expect(grid(page)).toHaveAttribute("data-gutter", "2"); // "3)" is two characters
  await page.keyboard.press("Escape");
  await page.keyboard.press("3"); // number-select still works with the gutter on
  await page.keyboard.press("Enter");
  await expect(panel(page).locator(".ph")).toContainText("NVDA | DES");

  await cmd(page, "SETTINGS ROWNUMBERS OFF");
  await cmd(page, "Q AAPL MSFT NVDA");
  await expect(grid(page)).toHaveAttribute("data-gutter", "0");
});

test("GUI: no gutter by default, SETTINGS ROWNUMBERS ON adds it", async ({ page }) => {
  await openApp(page, { mode: "gui" });
  await cmd(page, "Q AAPL MSFT NVDA");
  await expect(grid(page).locator(".sr")).toContainText("AAPL");
  await expect(grid(page)).toHaveAttribute("data-gutter", "0");
  await cmd(page, "SETTINGS ROWNUMBERS ON");
  await cmd(page, "Q AAPL MSFT NVDA");
  await expect(grid(page)).toHaveAttribute("data-gutter", "2");
});

test("WEI: numbers count data rows only (section headers have none)", async ({ page }) => {
  await openApp(page);
  await cmd(page, "WEI");
  await expect(grid(page).locator(".sr")).not.toHaveText("");
  // More than 9 data rows, so the widest number is two digits plus ")".
  await expect(grid(page)).toHaveAttribute("data-gutter", "3");
});

test("WEI: a 2DAY column and one batched sparks request", async ({ page }) => {
  await openApp(page);
  await cmd(page, "WEI");
  await expect(grid(page).locator(".sr")).not.toHaveText("");
  await expect(grid(page)).toHaveAttribute("data-cols", /(^|,)2DAY(,|$)/);
  await expect.poll(() => sparkCalls.length).toBe(1); // one request for the whole board, never one per symbol
  expect(sparkCalls[0].length).toBeGreaterThan(10);
  // The .sr summary and CSV keep their old columns: the helper columns are left out.
  await expect(grid(page).locator(".sr")).not.toContainText("2DAY");
});

test("FX and CMDTY get the 2DAY column too", async ({ page }) => {
  await openApp(page);
  for (const code of ["FX", "CMDTY"]) {
    await cmd(page, code);
    await expect(grid(page).locator(".sr")).not.toHaveText("");
    await expect(grid(page)).toHaveAttribute("data-cols", /(^|,)2DAY(,|$)/);
  }
});

test("a failed sparks request is said on the board's first line", async ({ page }) => {
  await page.route("**/api/sparks?**", (r) => r.abort());
  await openApp(page);
  await cmd(page, "WEI");
  await expect(panel(page).locator(".line").first()).toContainText("2DAY LINES");
});
