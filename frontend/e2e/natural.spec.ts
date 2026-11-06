import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";
import { bars, env, now, quote } from "./p19util";

/**
 * Plain-English commands and the Excel-style syntax hint (docs/specs/NEXT_FEATURES.md step 1).
 * Mocked routes only. The screener (company list) is counted: exact codes must never fetch it.
 */

const UNIVERSE: [string, string, number][] = [
  ["AAPL", "Apple Inc. Common Stock", 3e12],
  ["APLE", "Apple Hospitality REIT, Inc. Common Shares", 3e9],
  ["MSFT", "Microsoft Corporation Common Stock", 3.1e12],
  ["GOOGL", "Alphabet Inc. Class A Common Stock", 2e12],
  ["GOOG", "Alphabet Inc. Class C Capital Stock", 2e12],
  ["ZAC", "Zeta Alpha Corp Common Stock", 5e9],
  ["ZBC", "Zeta Beta Corp Common Stock", 4e9],
  ["TSLA", "Tesla, Inc. Common Stock", 8e11],
];
const screener = () => ({
  columns: ["symbol", "name", "last", "chg", "pct", "volume", "mcap", "country", "ipo", "sector", "industry"],
  rows: UNIVERSE.map(([s, n, cap]) => [s, n, 100, 1, 0.5, 1_000_000, cap, 1, 1990, 1, 1]),
  sectors: ["", "Technology"], industries: ["", "Computers"], countries: ["", "United States"],
  count: UNIVERSE.length, as_of_text: null, market: "US", source: "nasdaq_screener:fixture", as_of: now(),
});

async function mocks(page: Page) {
  const seen = { screener: 0, history: [] as URL[] };
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((msg) => {
      const f = JSON.parse(String(msg));
      if (f[0] === "ping") route.send(JSON.stringify(["pong", f[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s) => [s, env(quote(s, 100))])) } });
  });
  await page.route("**/api/history?**", (r) => {
    const u = new URL(r.request().url());
    seen.history.push(u);
    return r.fulfill({ json: env(bars(u.searchParams.get("symbol")!, u.searchParams.get("range") ?? "", u.searchParams.get("interval") ?? "")) });
  });
  await page.route("**/api/search?**", (r) => r.fulfill({ json: env([], { source: "yahoo" }) }));
  await page.route("**/api/screener**", (r) => {
    seen.screener++;
    return r.fulfill({ json: env(screener(), { source: "nasdaq_screener:fixture" }) });
  });
  await page.route("**/api/news?**", (r) => r.fulfill({ json: env({ kind: "top", query: null, failed: [], items: [] }) }));
  await page.route("**/api/profile?**", (r) => {
    const sym = new URL(r.request().url()).searchParams.get("symbol")!;
    return r.fulfill({ json: env({ symbol: sym, name: sym, exchange: "NasdaqGS", quote_type: "EQUITY", currency: "USD", summary: "x" }) });
  });
  return seen;
}

const type = async (page: Page, text: string, key: string | null = "Enter") => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  if (key) await page.keyboard.press(key);
};
const title = (page: Page) => page.locator('[data-panel="1"] .ph');

for (const mode of ["terminal", "gui"] as const) {
  test.describe(`plain English (${mode})`, () => {
    let seen: Awaited<ReturnType<typeof mocks>>;
    test.beforeEach(async ({ page }) => {
      seen = await mocks(page);
      await openApp(page, { mode });
    });

    test("a phrase opens the chart and teaches the code", async ({ page }) => {
      await type(page, "apple stock price chart");
      await expect(title(page)).toContainText("AAPL | GP");
      await expect(page.locator(".msg.info")).toHaveText("APPLE STOCK PRICE CHART -> AAPL GP");
    });

    test("range words", async ({ page }) => {
      await type(page, "microsoft 5 year chart");
      await expect(title(page)).toContainText("MSFT | GP");
      await expect.poll(() => seen.history.some((u) => u.searchParams.get("symbol") === "MSFT" && u.searchParams.get("range")?.toLowerCase() === "5y")).toBe(true);
    });

    test("a bare company name loads the security", async ({ page }) => {
      await type(page, "apple");
      await expect(title(page)).toContainText("AAPL");
      await expect(page.locator(".msg.info")).toHaveText("APPLE -> AAPL");
    });

    // CHANGED ON PURPOSE (NL_V2): "alphabet" is one company now (GOOGL, the most traded class), so the ambiguous name is two
    // similar-size companies ("zeta"). The share-class case is the next test.
    test("an ambiguous name asks, then runs the pick", async ({ page }) => {
      await type(page, "zeta 1 year chart");
      const ac = page.locator(".ac");
      await expect(ac).toContainText("ZAC GP 1Y");
      await expect(ac).toContainText("ZBC GP 1Y");
      await expect(page.locator(".msg.info")).toContainText("DID YOU MEAN");
      // On a slow CI runner the list above can still be the previous keystroke's (suggestions re-render after each key);
      // an ArrowDown that lands while it is briefly empty steps command history instead and nothing is highlighted.
      // So retry the whole type + ArrowDown until a row is highlighted, then read it.
      await expect(async () => {
        await page.keyboard.press("ArrowDown");
        if (await page.locator(".ac .on").count()) return;
        await page.locator("#cmdline").fill("");
        await page.keyboard.type("zeta 1 year chart");
        await expect(ac).toContainText("ZBC GP 1Y", { timeout: 1000 });
        await page.keyboard.press("ArrowDown");
        await expect(page.locator(".ac .on")).toHaveCount(1, { timeout: 1000 });
      }).toPass({ timeout: 10_000 });
      const picked = (await page.locator(".ac .on span").first().textContent({ timeout: 2000 }))!; // e.g. "ZBC GP 1Y"
      await page.keyboard.press("Enter");
      await expect(title(page)).toContainText(`${picked.split(" ")[0]} | GP`);
      await expect(page.locator("#cmdline")).toHaveValue("");
    });

    test("share classes of one company are not a question: alphabet is GOOGL", async ({ page }) => {
      await type(page, "alphabet stock 5 years");
      await expect(title(page)).toContainText("GOOGL | GP");
    });

    test("the preview line shows what Enter will run", async ({ page }) => {
      await type(page, "tesla news", null);
      await expect(page.locator(".ac")).toContainText("TSLA N");
      await page.keyboard.press("Tab");
      await expect(page.locator("#cmdline")).toHaveValue("TSLA N");
    });

    test("a comparison sentence opens GP with VS", async ({ page }) => {
      await type(page, "apple vs microsoft 1 year");
      await expect(title(page)).toContainText("AAPL | GP");
      await expect(page.locator(".msg.info")).toHaveText("APPLE VS MICROSOFT 1 YEAR -> AAPL GP 1Y VS MSFT");
      await expect.poll(() => seen.history.some((u) => u.searchParams.get("symbol") === "MSFT")).toBe(true);
    });

    test("a comparison with an unknown name says which", async ({ page }) => {
      await type(page, "apple vs zzzqqq");
      await expect(page.locator(".msg.err")).toContainText("UNKNOWN COMPANY: ZZZQQQ");
    });

    test("a screener sentence opens EQS", async ({ page }) => {
      await type(page, "tech stocks under 50 dollars");
      await expect(title(page)).toContainText("EQS");
      await expect(page.getByTestId("eqs-interp")).toContainText("SHOWING:");
    });

    test("nonsense keeps the normal error", async ({ page }) => {
      await type(page, "xyzzy blorp");
      await expect(page.locator(".msg.err")).toContainText("UNKNOWN FUNCTION");
    });

    test("exact codes never fetch the company list", async ({ page }) => {
      await type(page, "MSFT GP");
      await expect(title(page)).toContainText("MSFT | GP");
      await type(page, "AAPL DES");
      await expect(title(page)).toContainText("AAPL | DES");
      await page.waitForTimeout(400);
      expect(seen.screener).toBe(0);
    });

    test("syntax hint bolds the argument being typed", async ({ page }) => {
      await type(page, "AAPL GP ", null);
      const hint = page.getByTestId("syntax-hint");
      await expect(hint).toContainText("GP");
      await expect(hint.locator("b")).toHaveText("[1D..MAX]");
      await expect(page.getByTestId("syntax-values")).toContainText("1Y");
      await page.keyboard.type("5Y ");
      await expect(hint.locator("b")).toHaveText("[D|W|MO|5MIN|1H]");
      await page.keyboard.press("Escape");
      await expect(hint).toHaveCount(0);
    });

    test("typing a value lists matches and Tab completes", async ({ page }) => {
      await type(page, "AAPL GP 5", null);
      await expect(page.locator(".ac")).toContainText("5Y");
      await page.keyboard.press("Tab");
      await expect(page.locator("#cmdline")).toHaveValue("AAPL GP 5D ");
    });
  });
}
