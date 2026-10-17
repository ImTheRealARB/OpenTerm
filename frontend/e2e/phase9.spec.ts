import { readFile } from "node:fs/promises";
import { expect, test, type Download, type Page } from "@playwright/test";

// Mocked routes only (no network). The series below are synthetic test data made up in this file.
const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "yahoo", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });
const quote = (symbol: string, price: number) => ({
  symbol, name: `${symbol} NAME`, currency: "USD", exchange: "X", tz: "UTC", price, prev_close: price * 0.99,
  change: price * 0.01, change_pct: 1.01, open: null, high: price * 1.01, low: price * 0.98, volume: 1000, high_52w: null,
  low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now(),
});

const N = 800;
const T0 = Math.floor(now() / 86400) * 86400 - (N - 1) * 86400;
const T = Array.from({ length: N }, (_, i) => T0 + i * 86400);
const base = (i: number) => 100 + 10 * Math.sin(i / 7) + i * 0.05;
const dateOf = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);

/** AAA = base, BBB = 2 x AAA (corr +1), CCC = 1000 / AAA (corr -1); ZZZ has no data. */
const SERIES: Record<string, (i: number) => number> = { AAA: base, BBB: (i) => 2 * base(i), CCC: (i) => 1000 / base(i) };
const bars = (symbol: string, range: string, interval: string, withAdj = true) => {
  const f = SERIES[symbol] ?? base;
  const c = T.map((_, i) => f(i));
  return {
    symbol, range, interval, currency: "USD", exchange: "X", tz: "UTC", t: T, o: c, h: c.map((x) => x + 1), l: c.map((x) => x - 1), c,
    v: c.map(() => 1_000_000), adj: withAdj ? c.map((x) => x * 0.98) : null, source: "yahoo", as_of: now(),
  };
};

const UNIVERSE = {
  columns: ["symbol", "name", "last", "chg", "pct", "volume", "mcap", "country", "ipo", "sector", "industry"],
  rows: [
    ["NVDA", "NVIDIA Corp", 180, 3.6, 2.04, 200e6, 4.4e12, 1, 1999, 1, 1],
    ["AMD", "Advanced Micro Devices", 160, -2, -1.2, 50e6, 2.6e11, 1, null, 1, 1],
    ["PFE", "Pfizer Inc", 28, 0.1, 0.36, 30e6, 1.6e11, 1, null, 2, 2],
    ["BABA", "Alibaba Group", 90, 1, 1.1, 10e6, 2.2e11, 2, 2014, 3, 3],
  ],
  sectors: ["", "Technology", "Health Care", "Consumer Discretionary"],
  industries: ["", "Semiconductors", "Biotechnology", "Catalog/Specialty Distribution"],
  countries: ["", "United States", "China"],
  count: 4, as_of_text: "Data as of Oct 16, 2026 4:15 PM ET", market: "us", source: "nasdaq_screener", as_of: now(),
};
const PEERS = {
  symbol: "AAPL", basis: "yahoo",
  self: { symbol: "AAPL", name: "Apple Inc.", market_cap: 4e12, sector: "Technology", industry: "Consumer Electronics" },
  peers: [
    { symbol: "MSFT", name: "Microsoft Corp", market_cap: 3.5e12, sector: "Technology", industry: "Software", score: 0.1 },
    { symbol: "GOOG", name: "Alphabet Inc", market_cap: 2.5e12, sector: "Communication", industry: "Internet", score: 0.09 },
  ],
};

interface Opts { screener?: unknown; peers?: unknown; histEnv?: object; failHistory?: string[] }

async function setup(page: Page, o: Opts = {}) {
  const requests: string[] = [];
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
    const sym = u.searchParams.get("symbol")!;
    requests.push(`${sym} ${u.searchParams.get("range")} ${u.searchParams.get("interval")}`);
    if (sym === "ZZZ") return r.fulfill({ status: 404, json: { error: "NO DATA FOR ZZZ", kind: "not_found" } });
    if (o.failHistory?.includes(sym)) return r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "yahoo: 503" } });
    return r.fulfill({ json: env(bars(sym, u.searchParams.get("range") ?? "", u.searchParams.get("interval") ?? ""), o.histEnv) });
  });
  await page.route("**/api/screener", (r) =>
    o.screener === undefined
      ? r.fulfill({ json: env(UNIVERSE, { source: "nasdaq_screener" }) })
      : r.fulfill({ status: 503, json: o.screener }),
  );
  await page.route("**/api/peers?**", (r) =>
    o.peers === undefined ? r.fulfill({ json: env(PEERS, { source: "yahoo_peers" }) }) : r.fulfill({ status: 404, json: o.peers }),
  );
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  return { requests };
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape"); // leave the command line: letters go to the panel
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const selected = (page: Page, id = 1) => panel(page, id).locator(".grid .sr");

/** Presses E in the focused panel and returns the downloaded file's name and text. */
async function exportCsv(page: Page): Promise<{ name: string; text: string }> {
  const [dl]: [Download, void] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("e")]);
  return { name: dl.suggestedFilename(), text: (await readFile((await dl.path())!, "utf-8")).replace(/^﻿/, "") };
}

test("HIST: newest bar first with adjusted close, interval maps to the API, E exports the table", async ({ page }) => {
  const { requests } = await setup(page);
  await run(page, "AAA HIST 6M W");
  const p = panel(page);
  await expect(p).toContainText("HISTORY 6M WEEKLY");
  await expect(p).toContainText(`${N} BARS`);
  await expect(p).toContainText("YAHOO");
  await expect(p).not.toContainText("NO ADJ CLOSE");
  expect(requests).toContain("AAA 6M 1wk");
  await expect(selected(page)).toContainText(dateOf(T[N - 1]));
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText(dateOf(T[N - 2]));

  const csv = await exportCsv(page);
  expect(csv.name).toMatch(/^HIST_AAA_6M_W.*\.csv$/);
  const lines = csv.text.trim().split(/\r?\n/);
  expect(lines[0]).toBe("DATE,OPEN,HIGH,LOW,CLOSE,ADJ CLOSE,CHG%,VOLUME");
  expect(lines).toHaveLength(N + 1);
  expect(lines[1].startsWith(dateOf(T[N - 1]))).toBe(true);
  await expect(page.locator(".msg")).toContainText(`EXPORTED ${N} ROWS`);

  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("AAA | GP");
});

test("HIST: bad args are reported; stale and fallback data are labelled", async ({ page }) => {
  await setup(page, { histEnv: { stale: true, age_s: 400, source: "yahoo", fallback_from: ["stooq"] } });
  await run(page, "AAA HIST BOGUS");
  const p = panel(page);
  await expect(p).toContainText("CANNOT READ BOGUS");
  await expect(p).toContainText("STALE");
  await expect(p).toContainText("FALLBACK FROM STOOQ");
});

test("HIST: provider down shows the error with its detail", async ({ page }) => {
  await setup(page, { failHistory: ["AAA"] });
  await run(page, "AAA HIST");
  await expect(panel(page)).toContainText("PROVIDER DOWN");
  await expect(panel(page)).toContainText("yahoo: 503");
});

test("EQS: filters the universe, sorts, drills into DES, exports the matches", async ({ page }) => {
  await setup(page);
  await run(page, "EQS SECTOR=TECH");
  const p = panel(page);
  await expect(p).toContainText("4 IN UNIVERSE");
  await expect(p).toContainText("2 MATCH");
  await expect(p).toContainText("SECTOR=TECHNOLOGY");
  await expect(p).toContainText("NASDAQ_SCREENER");
  await expect(p).toContainText("DATA AS OF OCT 16, 2026 4:15 PM ET");
  await expect(selected(page)).toContainText("NVDA"); // default sort: market cap, largest first
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("AMD");

  const csv = await exportCsv(page);
  expect(csv.name).toMatch(/^EQS_SECTOR_TECH.*\.csv$/);
  const lines = csv.text.trim().split(/\r?\n/);
  expect(lines[0]).toBe("SYMBOL,NAME,LAST,CHG,%CHG,VOLUME,MKT CAP,CTRY,SECTOR,INDUSTRY,IPO");
  expect(lines).toHaveLength(3);
  expect(lines[1].startsWith("NVDA,NVIDIA Corp,")).toBe(true);
  expect(lines[1]).toContain("United States,Technology,Semiconductors,1999");

  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("AMD | DES");

  await run(page, "EQS MCAP>1T COUNTRY=US SORT=PCT");
  await expect(p).toContainText("1 MATCH");
  await expect(selected(page)).toContainText("NVDA");
  await run(page, "EQS COUNTRY=CN");
  await expect(selected(page)).toContainText("BABA");
});

test("EQS: bad terms and empty results are reported, never silently ignored", async ({ page }) => {
  await setup(page);
  await run(page, "EQS FOO=1 MCAP>9T");
  await expect(panel(page)).toContainText("UNKNOWN FIELD FOO");
  await expect(panel(page)).toContainText("0 MATCH");
  await run(page, "EQS SECTOR=NONESUCH");
  await expect(panel(page)).toContainText("NO SECTOR MATCHES NONESUCH");
});

test("EQS: PROVIDER DOWN shows source detail and no rows", async ({ page }) => {
  await setup(page, { screener: { error: "PROVIDER DOWN", kind: "unavailable", detail: "nasdaq_screener: timeout" } });
  await run(page, "EQS");
  await expect(panel(page)).toContainText("PROVIDER DOWN");
  await expect(panel(page)).toContainText("nasdaq_screener: timeout");
  await expect(panel(page)).not.toContainText("MATCH");
});

test("CORR: matrix, cursor, chart the pair, export", async ({ page }) => {
  await setup(page);
  await run(page, "CORR AAA BBB CCC 1Y");
  const p = panel(page);
  await expect(p).toContainText("1Y DAILY LOG RETURNS");
  await expect(p).toContainText(`${N - 1} RETURNS`);
  await expect(p).toContainText("ADJUSTED CLOSES");
  const row = (i: number) => p.locator(`.corr-t tbody tr:nth-child(${i}) td`);
  await expect(row(1)).toHaveText(["1.00", "1.00", "-1.00"]);
  await expect(row(3)).toHaveText(["-1.00", "-1.00", "1.00"]);
  await expect(row(1).nth(2)).toHaveClass(/h-m3/);
  await expect(row(1).nth(1)).toHaveClass(/h-p3/);
  await expect(p.locator(".sr")).toContainText("AAA / AAA 1.00");
  await page.keyboard.press("l");
  await page.keyboard.press("l");
  await expect(p.locator(".sr")).toContainText("AAA / CCC -1.00");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("BBB / CCC -1.00");

  const csv = await exportCsv(page);
  expect(csv.name).toMatch(/^CORR_1Y_AAA_BBB_CCC.*\.csv$/);
  expect(csv.text.trim().split(/\r?\n/)).toEqual([",AAA,BBB,CCC", "AAA,1,1,-1", "BBB,1,1,-1", "CCC,-1,-1,1"]);

  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("BBB | GP");
});

test("CORR: usage error, and a symbol with no data is named and left out", async ({ page }) => {
  const { requests } = await setup(page);
  await run(page, "CORR AAA");
  await expect(panel(page)).toContainText("USAGE: CORR SYM SYM");
  expect(requests).toHaveLength(0);
  await run(page, "CORR AAA BBB ZZZ");
  await expect(panel(page)).toContainText("ZZZ: NO DATA FOR ZZZ");
  await expect(panel(page).locator(".corr-t tbody tr")).toHaveCount(2);
});

test("COMP: subject first, peers with returns, peer median, drill down, export", async ({ page }) => {
  await setup(page);
  await run(page, "AAPL COMP");
  const p = panel(page);
  await expect(p).toContainText("2 FOUND");
  await expect(p).toContainText("YAHOO RECOMMENDED");
  await expect(p).toContainText("TECHNOLOGY / CONSUMER ELECTRONICS");
  await expect(selected(page)).toContainText("AAPL");
  await expect(selected(page)).toContainText("SELF");
  await page.keyboard.press("G");
  await expect(selected(page)).toContainText("MEDIAN");

  const csv = await exportCsv(page);
  expect(csv.name).toMatch(/^COMP_AAPL.*\.csv$/);
  const lines = csv.text.trim().split(/\r?\n/);
  expect(lines[0]).toBe("ROLE,SYMBOL,NAME,PRICE,%CHG,MKT CAP,1M%,3M%,6M%,1Y%");
  expect(lines.map((l) => l.split(",")[1])).toEqual(["SYMBOL", "AAPL", "MSFT", "GOOG", "MEDIAN"]);
  // Every period return came from the 2Y history (never blank when the history reaches back far enough).
  expect(lines[1].split(",").slice(6).every((c) => c.endsWith("%") && c !== "-")).toBe(true);

  await page.keyboard.press("k");
  await page.keyboard.press("k");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("MSFT | DES");
});

test("COMP: a peer whose history fails is named; no peers at all is an error", async ({ page }) => {
  await setup(page, { failHistory: ["GOOG"] });
  await run(page, "AAPL COMP");
  await expect(panel(page)).toContainText("MISSING: GOOG HISTORY: PROVIDER DOWN");
  await expect(selected(page)).toContainText("AAPL");
});

test("COMP: NO PEERS FOUND is shown with its detail", async ({ page }) => {
  await setup(page, { peers: { error: "NO PEERS FOUND", kind: "not_found", detail: "yahoo_peers: empty" } });
  await run(page, "AAPL COMP");
  await expect(panel(page)).toContainText("NO PEERS FOUND");
  await expect(panel(page)).toContainText("yahoo_peers: empty");
});

test("Alt+X exports the focused panel's table; panels without a table say so", async ({ page }) => {
  await setup(page);
  await run(page, "EQS SECTOR=HEALTH");
  await expect(panel(page)).toContainText("1 MATCH");
  const [dl] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("Alt+x")]);
  expect(dl.suggestedFilename()).toMatch(/^EQS_SECTOR_HEALTH.*\.csv$/);
  await run(page, "HELP");
  await page.keyboard.press("Alt+x");
  await expect(page.locator(".msg")).toContainText("NOTHING TO EXPORT");
});

test("EQS: a valid filter with no matches says so", async ({ page }) => {
  await setup(page);
  await run(page, "EQS MCAP>9T");
  await expect(panel(page)).toContainText("0 MATCH");
  await expect(panel(page)).toContainText("NO SECURITIES MATCH THE FILTER");
});
