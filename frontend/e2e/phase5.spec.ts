import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";

const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "yahoo", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
const PRICES: Record<string, number> = { "EURUSD=X": 1.08523, "USDEUR=X": 0.86, "USDJPY=X": 150.5, "USDINR=X": 88.0 };
const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} NAME`, currency: "USD", exchange: "X", tz: "America/New_York", price, prev_close: price * 0.99,
  change: price * 0.01, change_pct: 1.01, open: null, high: price * 1.01, low: price * 0.98, volume: 1000, high_52w: null,
  low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now(),
});

const NEWS = [
  { id: "a1", title: "Brent oil touches $110 as Iran escalates Hormuz attacks", url: "https://www.cnbc.com/a1", publisher: "CNBC", published: now() - 120, summary: "U.S. crude oil prices rose sharply Friday.", source: "rss" },
  { id: "a2", title: "Nowhere to hide: Tech selloff hits software and chip stocks", url: "https://www.marketwatch.com/a2", publisher: "MARKETWATCH", published: now() - 600, summary: "Software and semis fell together.", source: "rss" },
  { id: "a3", title: "10 smallcap stocks surge up to 65% in 3 months", url: "https://economictimes.indiatimes.com/a3", publisher: "ECONOMIC TIMES", published: now() - 7200, summary: null, source: "rss" },
];
const mover = (symbol: string, price: number, change: number, change_pct: number, volume: number | null = null) => ({ symbol, name: `${symbol} Corp`, price, change, change_pct, volume });
const MOVERS = {
  tables: {
    GAINERS: [mover("XLAB", 2.35, 0.99, 72.79), mover("ZTG", 0.705, 0.082, 13.16)],
    LOSERS: [mover("MDXH", 0.2066, -0.397, -65.77)],
    ACTIVE: [mover("HODO", 0.0928, 0.0253, 37.48, 561137454)],
    DOLLAR: [mover("SPY", 763.23, -8.56, -1.11)],
    NDX100: [mover("ADBE", 245.2, -6.47, -2.57)],
  },
  table_as_of: { GAINERS: "Data as of Oct 16, 2026 4:15 PM ET", LOSERS: "Data as of Oct 16, 2026 4:15 PM ET" },
  as_of_text: "Data as of Oct 16, 2026 4:15 PM ET", market_time: 1792196100, source: "nasdaq", as_of: now(),
};
const coin = (symbol: string, name: string, rank: number, price: number) => ({
  symbol, name, rank, quote: "USD", price, change_pct_1h: 0.02, change_pct_24h: -0.58, change_pct_7d: -1.35, high_24h: price * 1.01,
  low_24h: price * 0.99, volume_24h: 2.5e10, market_cap: 1.64e12, updated: now() - 30, source: "coingecko", as_of: now(),
});

let ws: WebSocketRoute | null = null;
const subs: string[][] = [];

async function setup(page: Page) {
  ws = null;
  subs.length = 0;
  const lists = new Map<string, string[]>();
  const writes: string[] = [];
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
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, PRICES[s] ?? 100 + i))])) } });
  });
  await page.route("**/api/watchlists**", (r) => {
    const req = r.request();
    const name = decodeURIComponent(new URL(req.url()).pathname.split("/api/watchlists")[1].replace(/^\//, "")).toUpperCase();
    const body = req.postDataJSON?.() ?? null;
    if (req.method() !== "GET") writes.push(`${req.method()} ${name} ${JSON.stringify(body)}`);
    if (!name) {
      const out = [...lists].map(([n, s]) => ({ name: n, count: s.length, updated_at: now() }));
      return r.fulfill({ json: { watchlists: out.sort((a, b) => a.name.localeCompare(b.name)) } });
    }
    const cur = lists.get(name);
    if (req.method() === "PATCH") {
      if (!cur && !body.add?.length) return r.fulfill({ status: 404, json: { error: `NO WATCHLIST ${name}`, kind: "not_found" } });
      const merged = [...new Set([...(cur ?? []), ...(body.add ?? [])])].filter((s) => !(body.remove ?? []).includes(s));
      lists.set(name, merged);
      return r.fulfill({ json: { name, symbols: merged, updated_at: now() } });
    }
    if (req.method() === "PUT") {
      lists.set(name, body.symbols);
      return r.fulfill({ json: { name, symbols: body.symbols, updated_at: now() } });
    }
    if (!cur) return r.fulfill({ status: 404, json: { error: `NO WATCHLIST ${name}`, kind: "not_found" } });
    if (req.method() === "DELETE") {
      lists.delete(name);
      return r.fulfill({ json: { deleted: name } });
    }
    return r.fulfill({ json: { name, symbols: cur, updated_at: now() } });
  });
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  return { lists, writes };
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape"); // leave the command line: letters go to the panel
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
/** The canvas grid mirrors its selected row into a visually hidden live region. */
const selected = (page: Page, id = 1) => panel(page, id).locator(".grid .sr");

test("WL: ADD creates a list, D removes with undo, the index deletes on Del twice", async ({ page }) => {
  const { writes } = await setup(page);
  await run(page, "WL tech ADD aapl msft nvda");
  const p = panel(page);
  await expect(p.locator(".ph")).toContainText("WL");
  await expect(p).toContainText("WATCHLIST TECH");
  await expect(p).toContainText("3 SECURITIES");
  expect(writes[0]).toBe('PATCH TECH {"add":["AAPL","MSFT","NVDA"],"remove":[]}');
  await expect.poll(() => subs.flat().sort().join(",")).toBe("AAPL,MSFT,NVDA");

  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("MSFT");
  await page.keyboard.press("d");
  await expect(p).toContainText("2 SECURITIES");
  await expect(page.locator(".msg")).toContainText("REMOVED MSFT FROM TECH");
  expect(writes[1]).toBe('PATCH TECH {"remove":["MSFT"]}');
  await page.keyboard.press("u");
  await expect(p).toContainText("3 SECURITIES");
  expect(writes[2]).toBe('PUT TECH {"symbols":["AAPL","MSFT","NVDA"]}');

  await page.keyboard.press("a");
  await expect(page.locator("#cmdline")).toHaveValue("WL TECH ADD ");
  await page.keyboard.press("Escape");

  await run(page, "WL");
  await expect(p).toContainText("WATCHLISTS");
  await expect(p.locator("tr.on")).toContainText("TECH");
  await expect(p.locator("tr.on")).toContainText("3");
  await page.keyboard.press("Delete");
  await expect(p).toContainText("DELETE? PRESS DEL AGAIN");
  await page.keyboard.press("Delete");
  await expect(p).toContainText("NO WATCHLISTS");
  expect(writes[3]).toBe("DELETE TECH null");
});

test("WL: autocomplete offers saved list names", async ({ page }) => {
  const { lists } = await setup(page);
  lists.set("INDIA", ["RELIANCE.NS"]);
  await page.keyboard.press("Control+k");
  await page.keyboard.type("WL IN");
  await expect(page.locator(".ac")).toContainText("INDIA");
  await expect(page.locator(".ac")).toContainText("1 SYMBOLS");
});

test("N: top stories, J/K select, Enter opens the article, keyword search, errors show their cause", async ({ page }) => {
  await setup(page);
  const asked: string[] = [];
  await page.route("**/api/news**", (r) => {
    const u = new URL(r.request().url());
    asked.push(u.search);
    const q = u.searchParams.get("q");
    if (q === "ZZZ") return r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "gdelt: rate_limited (429 from upstream)" } });
    const kind = q ? "keyword" : u.searchParams.get("symbol") ? "symbol" : "top";
    return r.fulfill({ json: env({ kind, query: q?.toUpperCase() ?? null, items: NEWS, failed: kind === "top" ? ["BBC BUSINESS"] : [] }, { source: "rss" }) });
  });
  await run(page, "N");
  const p = panel(page);
  await expect(p).toContainText("TOP NEWS");
  await expect(p).toContainText("3 HEADLINES");
  await expect(p).toContainText("NOT ANSWERING: BBC BUSINESS");
  await expect(selected(page)).toContainText("Brent oil touches $110");
  await expect(p.locator(".summary")).toContainText("U.S. crude oil prices rose sharply");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("Nowhere to hide");
  // The article opens in a new tab; answer it locally so the test never touches the network.
  await page.context().route("https://www.marketwatch.com/**", (r) => r.fulfill({ body: "article" }));
  const tab = page.context().waitForEvent("page");
  await page.keyboard.press("Enter");
  expect((await tab).url()).toBe("https://www.marketwatch.com/a2");

  await page.bringToFront();
  await run(page, "N rate cut");
  await expect(p).toContainText("NEWS SEARCH: RATE CUT");
  expect(asked).toContain("?q=RATE+CUT");
  await run(page, "N zzz");
  await expect(p).toContainText("PROVIDER DOWN");
  await expect(p).toContainText("gdelt: rate_limited");
});

test("WEI, CMDTY and FX boards: sections, live subscription, Enter charts", async ({ page }) => {
  await setup(page);
  await run(page, "WEI");
  const p = panel(page);
  await expect(p).toContainText("WORLD EQUITY INDICES");
  await expect(p).toContainText("31 INDICES");
  await expect(selected(page)).toContainText("S&P 500"); // the cursor starts on the first index, not a header
  await expect.poll(() => subs.flat()).toContain("^NSEI");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("^GSPC | GP");

  await run(page, "CMDTY");
  await expect(p).toContainText("COMMODITIES");
  await expect(p).toContainText("19 CONTRACTS");
  await expect(selected(page)).toContainText("WTI CRUDE");
  await expect(selected(page)).toContainText("USD/BBL");
  for (let i = 0; i < 5; i++) await page.keyboard.press("j"); // five energy rows down, past the METALS header
  await expect(selected(page)).toContainText("GOLD");

  await run(page, "FX");
  await expect(p).toContainText("CURRENCIES");
  await expect(selected(page)).toContainText("EURUSD=X");
  await expect(selected(page)).toContainText("1.0852");
});

test("FXC: cross matrix triangulated from USD legs, live ticks recompute it", async ({ page }) => {
  await setup(page);
  await run(page, "FXC USD EUR JPY");
  const p = panel(page);
  await expect(p).toContainText("CROSS RATES");
  await expect(p).toContainText("3 CURRENCIES");
  await expect(p).toContainText("TRIANGULATED VIA USD");
  await expect(selected(page)).toContainText("USD");
  await expect(selected(page)).toContainText("0.86000");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("175.00"); // 1 EUR = 150.5 / 0.86 JPY
  await expect.poll(() => subs.flat().sort().join(",")).toBe("USDEUR=X,USDJPY=X");
  ws!.send(JSON.stringify(["T", [["USDJPY=X", 172.0, null, null, null, null, null, Date.now(), "y"]]]));
  await page.keyboard.press("k");
  await page.keyboard.press("j"); // re-select the EUR row to refresh the mirrored text
  await expect(selected(page)).toContainText("200.00"); // 172 / 0.86
});

test("MOV: tabs by number keys, Enter describes the security", async ({ page }) => {
  await setup(page);
  await page.route("**/api/movers", (r) => r.fulfill({ json: env(MOVERS, { source: "nasdaq" }) }));
  await run(page, "MOV");
  const p = panel(page);
  await expect(p).toContainText("US MOVERS");
  await expect(p).toContainText("GAINERS");
  await expect(p).toContainText("DATA AS OF OCT 16, 2026 4:15 PM ET");
  await expect(selected(page)).toContainText("XLAB");
  await page.keyboard.press("2");
  await expect(p.locator(".tabs .on")).toHaveText("2 LOSERS");
  await expect(selected(page)).toContainText("MDXH");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("MDXH | DES");
});

test("CRYP: CoinGecko board with source and age; Enter charts the USD pair", async ({ page }) => {
  await setup(page);
  const seen: string[] = [];
  await page.route("**/api/crypto**", (r) => {
    seen.push(new URL(r.request().url()).search);
    return r.fulfill({ json: env({ vs: "USD", coins: [coin("BTC", "Bitcoin", 1, 81588), coin("ETH", "Ethereum", 2, 2950.12)] }, { source: "coingecko" }) });
  });
  await run(page, "CRYP");
  const p = panel(page);
  await expect(p).toContainText("CRYPTO");
  await expect(p).toContainText("COINGECKO");
  await expect(selected(page)).toContainText("BTC");
  await expect(selected(page)).toContainText("Bitcoin");
  await expect(selected(page)).toContainText("81,588.00");
  await page.keyboard.press("j");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("ETH-USD | GP");
  expect(seen[0]).toBe("?vs=USD");
});

test("every Phase 5 function is listed as ready in HELP", async ({ page }) => {
  await setup(page);
  await run(page, "HELP");
  for (const code of ["N", "WL", "WEI", "MOV", "FX", "FXC", "CRYP", "CMDTY"]) {
    const row = panel(page).locator("tr").filter({ has: page.locator("td.acc", { hasText: new RegExp(`^${code}$`) }) });
    await expect(row).toContainText("READY");
  }
});
