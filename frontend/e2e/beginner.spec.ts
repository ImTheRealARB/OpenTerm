import { expect, test, type Locator, type Page } from "@playwright/test";
import { openApp } from "./app";
import { bars, env, now, quote } from "./p19util";

/**
 * Part 1A of docs/specs/GUI_SIMPLE_AND_BUGS.md: the beginner task suite.
 *
 * Ten everyday tasks, each run in GUI mode with the MOUSE ONLY. Nothing here types a function code (GP, DES, WL...).
 * Typing a company name ("apple") into a search box is allowed; typing a number into a form field is too.
 * Every click goes through `clicker()` so the test can assert "at most 4 clicks" after it has asserted the outcome.
 *
 * Each test is written as the IDEAL beginner flow (plain-word buttons, company-name search, glossary tooltip, "Add a stock"
 * buttons in empty states). All ten pass now; a task that regresses should be marked `test.fail()` again (tests-first rule:
 * the suite stays green, and a strict pass turns red, so the build step must delete the marker). To see why a test fails,
 * run with BEGINNER_REAL=1 (the markers are skipped and the real failure prints).
 *
 * Mocked routes only (no network). Watchlists, portfolios and alerts are small in-memory fakes so the tests can read what was saved.
 * docs/review/cloud/BEGINNER_CLICKS.md lists what the UI needs (files, components, testids) for each marked test to pass.
 */

// A short action timeout: a marked test must FAIL at its first missing button (an expected failure), not time out (which Playwright
// reports as a real failure even under test.fail).
test.use({ actionTimeout: 3_000 });


/** Counts mouse clicks. Hover and typing are not clicks; they are not counted. */
function clicker() {
  let n = 0;
  return {
    click: async (loc: Locator) => {
      n++;
      await loc.click();
    },
    get count() {
      return n;
    },
  };
}

// A tiny stock universe for the company-name search (columnar screener payload, see ScreenerPayload in net/api.ts).
const UNIVERSE: [string, string, number][] = [
  ["AAPL", "Apple Inc. Common Stock", 187.25],
  ["MSFT", "Microsoft Corporation Common Stock", 410.1],
  ["NVDA", "NVIDIA Corporation Common Stock", 120.5],
  ["TSLA", "Tesla, Inc. Common Stock", 245.8],
];
const screener = () => ({
  columns: ["symbol", "name", "last", "chg", "pct", "volume", "mcap", "country", "ipo", "sector", "industry"],
  rows: UNIVERSE.map(([s, n, p]) => [s, n, p, 1, 0.5, 1_000_000, 1e12, 1, 1990, 1, 1]),
  sectors: ["", "Technology"], industries: ["", "Computers"], countries: ["", "United States"],
  count: UNIVERSE.length, as_of_text: null, market: "US", source: "nasdaq_screener:fixture", as_of: now(),
});

const PROFILE = {
  name: "Apple Inc.", exchange: "NasdaqGS", quote_type: "EQUITY", currency: "USD", sector: "Technology", industry: "Consumer Electronics",
  market_cap: 2.9e12, enterprise_value: 3e12, pe: 31.4, forward_pe: 28.2, eps: 5.96, forward_eps: 6.6, dividend_yield: 0.005, beta: 1.2,
  price_to_book: 40, shares_out: 1.5e10, float_shares: 1.5e10, avg_volume: 5e7, employees: 160000, summary: "Makes phones.",
};

const HEADLINES = ["Stocks rally as inflation cools", "Oil slips on demand worries", "Chipmakers lead the Nasdaq higher"];

interface Mocks {
  errors: string[];
  history: URL[];
  quotes: string[];
  watchlists: Map<string, string[]>;
  portfolios: Map<string, { symbol: string; qty: number; cost: number | null }[]>;
  alerts: { symbol: string; op: string; unit: string; value: number }[];
  posts: { url: string; body: unknown }[];
}

async function setupGui(page: Page): Promise<Mocks> {
  const m: Mocks = { errors: [], history: [], quotes: [], watchlists: new Map(), portfolios: new Map(), alerts: [], posts: [] };
  page.on("pageerror", (e) => m.errors.push(String(e)));
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((msg) => {
      const f = JSON.parse(String(msg));
      if (f[0] === "ping") route.send(JSON.stringify(["pong", f[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    m.quotes.push(...syms);
    const price = (s: string) => UNIVERSE.find((u) => u[0] === s)?.[2] ?? 100;
    return r.fulfill({
      json: { results: Object.fromEntries(syms.map((s) => [s, s.startsWith("ZZ") ? { error: "NO DATA FOR SYMBOL" } : env(quote(s, price(s)))])) },
    });
  });
  await page.route("**/api/profile?**", (r) => {
    const sym = new URL(r.request().url()).searchParams.get("symbol")!;
    if (sym.startsWith("ZZ")) return r.fulfill({ status: 404, json: { error: `NO DATA FOR ${sym}`, kind: "not_found" } });
    return r.fulfill({ json: env({ symbol: sym, ...PROFILE }) });
  });
  await page.route("**/api/history?**", (r) => {
    const u = new URL(r.request().url());
    m.history.push(u);
    return r.fulfill({ json: env(bars(u.searchParams.get("symbol")!, u.searchParams.get("range") ?? "", u.searchParams.get("interval") ?? "")) });
  });
  // Yahoo name search (used only when the screener finds fewer than 3 matches): nothing extra in these tests.
  await page.route("**/api/search?**", (r) => r.fulfill({ json: env([], { source: "yahoo" }) }));
  await page.route("**/api/screener**", (r) => r.fulfill({ json: env(screener(), { source: "nasdaq_screener:fixture" }) }));
  await page.route("**/api/news?**", (r) =>
    r.fulfill({
      json: env({
        kind: "top", query: null, failed: [],
        items: HEADLINES.map((title, i) => ({ id: `n${i}`, title, url: `https://example.test/${i}`, publisher: "Test Wire", published: now() - 60 * (i + 1), summary: null, source: "rss" })),
      }),
    }),
  );

  // Watchlists: GET index, GET/PUT/PATCH/DELETE one.
  await page.route(/\/api\/watchlists(\/[^?]*)?(\?.*)?$/, async (r) => {
    const req = r.request();
    const name = decodeURIComponent(new URL(req.url()).pathname.split("/")[3] ?? "");
    if (!name) {
      return r.fulfill({ json: { watchlists: [...m.watchlists].map(([n, s]) => ({ name: n, count: s.length, updated_at: now() })) } });
    }
    if (req.method() === "PUT") m.watchlists.set(name, (req.postDataJSON() as { symbols: string[] }).symbols);
    if (req.method() === "PATCH") {
      const ch = req.postDataJSON() as { add?: string[]; remove?: string[] };
      const cur = (m.watchlists.get(name) ?? []).filter((s) => !(ch.remove ?? []).includes(s));
      m.watchlists.set(name, [...cur, ...(ch.add ?? []).filter((s) => !cur.includes(s))]);
    }
    if (req.method() === "DELETE") m.watchlists.delete(name);
    if (!m.watchlists.has(name)) return r.fulfill({ status: 404, json: { error: `NO WATCHLIST ${name}`, kind: "not_found" } });
    return r.fulfill({ json: { name, symbols: m.watchlists.get(name), updated_at: now() } });
  });

  // Portfolios: same shape; PATCH {add:[positions]} merges.
  await page.route(/\/api\/portfolios(\/[^?]*)?(\?.*)?$/, async (r) => {
    const req = r.request();
    const name = decodeURIComponent(new URL(req.url()).pathname.split("/")[3] ?? "");
    if (!name) {
      return r.fulfill({ json: { portfolios: [...m.portfolios].map(([n, p]) => ({ name: n, base: "USD", count: p.length, updated_at: now() })) } });
    }
    if (req.method() === "PUT") m.portfolios.set(name, (req.postDataJSON() as { positions: { symbol: string; qty: number; cost: number | null }[] }).positions);
    if (req.method() === "PATCH") {
      const ch = req.postDataJSON() as { add?: { symbol: string; qty: number; cost?: number | null }[]; set?: { symbol: string; qty: number; cost?: number | null }[] };
      const cur = m.portfolios.get(name) ?? [];
      for (const p of [...(ch.add ?? []), ...(ch.set ?? [])]) {
        const i = cur.findIndex((c) => c.symbol === p.symbol);
        const row = { symbol: p.symbol, qty: p.qty, cost: p.cost ?? null };
        if (i >= 0) cur[i] = row;
        else cur.push(row);
      }
      m.portfolios.set(name, cur);
    }
    if (!m.portfolios.has(name)) return r.fulfill({ status: 404, json: { error: `NO PORTFOLIO ${name}`, kind: "not_found" } });
    return r.fulfill({
      json: { name, base: "USD", updated_at: now(), positions: m.portfolios.get(name)!.map((p) => ({ ...p, currency: "USD", notes: null })) },
    });
  });

  // Alerts: GET list, POST create.
  await page.route(/\/api\/alerts(\?.*)?$/, async (r) => {
    const req = r.request();
    if (req.method() === "POST") {
      const a = req.postDataJSON() as { symbol: string; op: string; unit: string; value: number };
      m.alerts.push(a);
      m.posts.push({ url: "/api/alerts", body: a });
      return r.fulfill({ json: { id: m.alerts.length, ...a, status: "active", created_at: now(), triggered_at: null, trigger_price: null } });
    }
    return r.fulfill({
      json: { alerts: m.alerts.map((a, i) => ({ id: i + 1, ...a, status: "active", created_at: now(), triggered_at: null, trigger_price: null })) },
    });
  });

  // Backtests: only the submit is mocked (record it, answer "queued"). The result frames are not needed to prove the run started.
  await page.route("**/api/bt/**", (r) => {
    const req = r.request();
    const path = new URL(req.url()).pathname;
    if (path === "/api/bt/templates") return r.fulfill({ json: { templates: [{ id: "sma_cross", title: "SMA CROSS", summary: "Buy when the 20-day average is above the 50-day average.", code: "class SignalEngine: pass" }] } });
    if (path === "/api/bt/run") {
      m.posts.push({ url: path, body: req.postDataJSON() });
      return r.fulfill({ json: { id: "j1", kind: "bt.run", state: "queued", progress: 0, msg: "", cached: false } });
    }
    return r.fulfill({ json: { runs: [], strategies: [] } });
  });

  await openApp(page, { mode: "gui", welcome: true });
  return m;
}

const panel = (page: Page) => page.locator('[data-panel="1"]');
const header = (page: Page) => page.locator('[data-panel="1"] .ph');
const startHere = (page: Page, name: string | RegExp) => page.getByTestId("start-here").getByRole("button", { name });
const suggestion = (page: Page, symbol: string) => page.getByRole("option", { name: new RegExp(`\\b${symbol}\\b`) });

/** The beginner's search box. Typing a company name is allowed. Today `gui-symbol` takes a ticker only. */
async function search(page: Page, text: string) {
  const box = page.getByTestId("gui-symbol");
  await box.click(); // focusing the box is not counted: the beginner's first click is on the suggestion
  await box.fill(text);
}

// The welcome card (welcome: true) covers the workspace; a beginner closes it with one click. It is the same for every task and
// goes away for good after the first run, so it is not counted.
async function dismissWelcome(page: Page) {
  await page.getByTestId("welcome-close").click();
  await expect(page.getByTestId("welcome-card")).toHaveCount(0);
}

// 1. Look up Apple and see its price and P/E.
test("1. look up Apple and see its price and P/E", async ({ page }) => {
  const m = await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await search(page, "apple");
  await c.click(suggestion(page, "AAPL"));
  await expect(header(page)).toContainText("AAPL");
  await expect(panel(page)).toContainText("187.25"); // the price (mocked quote)
  await expect(panel(page)).toContainText("P/E"); // the label
  await expect(panel(page)).toContainText("31.4"); // the value (mocked profile)
  expect(m.errors).toEqual([]);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 2. Chart Tesla over 1 year.
test("2. chart Tesla over 1 year", async ({ page }) => {
  const m = await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await search(page, "tesla");
  await c.click(suggestion(page, "TSLA"));
  await c.click(startHere(page, "Stock chart"));
  await c.click(panel(page).getByRole("button", { name: "1Y", exact: true }));
  await expect(header(page)).toContainText("TSLA");
  await expect.poll(() => m.history.some((u) => u.searchParams.get("symbol") === "TSLA" && /^1y$/i.test(u.searchParams.get("range") ?? ""))).toBe(true);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 3. Make a watchlist with 3 stocks.
test("3. make a watchlist with 3 stocks", async ({ page }) => {
  const m = await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await c.click(startHere(page, "My watchlist"));
  await c.click(panel(page).getByRole("button", { name: "Add a stock" }));
  await page.getByTestId("pt-ask").fill("AAPL MSFT NVDA"); // typing symbols into the form, not a function code
  await c.click(panel(page).getByRole("button", { name: "Run" }));
  await expect.poll(() => [...m.watchlists.values()].map((s) => s.length)).toEqual([3]);
  await expect(panel(page).locator(".grid .sr")).toContainText(/AAPL|MSFT|NVDA/);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 4. See today's top market news.
test("4. see today's top market news", async ({ page }) => {
  await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await c.click(startHere(page, "Top news"));
  await expect(header(page)).toContainText("N");
  await expect(panel(page).locator(".grid .sr")).toContainText(HEADLINES[0]);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 5. See how the major world indices are doing.
test("5. see how the major world indices are doing", async ({ page }) => {
  const m = await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await c.click(startHere(page, "World markets"));
  await expect(header(page)).toContainText("WEI");
  await expect.poll(() => m.quotes.includes("^GSPC")).toBe(true);
  await expect(panel(page).locator(".grid .sr")).toContainText(/S&P 500|DOW|NASDAQ/i);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 6. Set a price alert on a stock.
test("6. set a price alert on a stock", async ({ page }) => {
  const m = await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await search(page, "apple");
  await c.click(suggestion(page, "AAPL"));
  await c.click(panel(page).getByRole("button", { name: "Set alert" }));
  await page.getByTestId("pt-ask").fill("200"); // a number in the form: "tell me when AAPL goes above ..."
  await c.click(panel(page).getByRole("button", { name: "Run" }));
  await expect.poll(() => m.alerts).toEqual([{ symbol: "AAPL", op: ">", unit: "price", value: 200 }]);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 7. Track a small portfolio (2 positions) and see its value.
test("7. track a small portfolio of 2 positions and see its value", async ({ page }) => {
  const m = await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await c.click(startHere(page, "My portfolio"));
  await c.click(panel(page).getByRole("button", { name: "Add a stock" }));
  await page.getByTestId("pt-ask").fill("AAPL 10 150, MSFT 5 300");
  await c.click(panel(page).getByRole("button", { name: "Run" }));
  await expect.poll(() => [...m.portfolios.values()].map((p) => p.length)).toEqual([2]);
  await expect(panel(page).getByTestId("port-summary")).toContainText(/value/i);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 8. Run a sample backtest from a starter template.
// (today templates exist only inside the strategy editor, reached by typing "BT EDIT name").
test("8. run a sample backtest from a starter template", async ({ page }) => {
  const m = await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await c.click(startHere(page, "Try a backtest"));
  await c.click(panel(page).getByTestId("bt-template").first());
  await c.click(panel(page).getByRole("button", { name: "Run backtest" }));
  await expect.poll(() => m.posts.some((p) => p.url === "/api/bt/run")).toBe(true);
  await expect(panel(page)).toContainText(/HISTORICAL SIMULATION|running|queued/i);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 9. Find out what a number on screen means (EPS).
test("9. find out what EPS means (a plain-English explanation appears)", async ({ page }) => {
  await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await search(page, "apple");
  await c.click(suggestion(page, "AAPL"));
  const term = panel(page).locator('[data-term="EPS"]').first();
  await term.hover(); // hover is not a click
  await expect(page.getByRole("tooltip")).toContainText(/earnings/i);
  await expect(page.getByRole("tooltip")).toContainText(/per share/i);
  // The same line shows for a keyboard user: focus the term.
  await page.mouse.move(0, 0);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await term.focus();
  await expect(page.getByRole("tooltip")).toContainText(/earnings/i);
  expect(c.count).toBeLessThanOrEqual(4);
});

// 10. Recover from an error (unknown symbol) without help.
test("10. recover from an unknown symbol without help", async ({ page }) => {
  await setupGui(page);
  await dismissWelcome(page);
  const c = clicker();
  await search(page, "zzzzqq");
  await page.getByTestId("gui-symbol").press("Enter"); // Enter is the keyboard equivalent of the Go button; not a click
  const note = panel(page).getByTestId("note-action");
  await expect(note.first()).toBeVisible();
  await expect(panel(page)).toContainText(/NO DATA/i); // exact error text stays
  await c.click(note.first()); // e.g. "Try AAPL"
  await expect(header(page)).toContainText(/AAPL|MSFT|NVDA|TSLA/);
  expect(c.count).toBeLessThanOrEqual(4);
});
