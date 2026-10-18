import { expect, test, type Page } from "@playwright/test";
import { env, now, panel, run, setup } from "./p19util";

// Phase 19 step 4 end-to-end tests (mocked routes only): SECF.

const UNIVERSE = {
  columns: ["symbol", "name", "last", "chg", "pct", "volume", "mcap", "country", "ipo", "sector", "industry"],
  rows: [
    ["AAPL", "Apple Inc. Common Stock", 200, 1, 0.5, 1e6, 3.4e12, 1, null, 1, 1],
    ["APLE", "Apple Hospitality REIT, Inc. Common Shares", 15, 0, 0, 1e6, 3.5e9, 1, null, 2, 2],
    ["MSFT", "Microsoft Corporation Common Stock", 400, 0, 0, 1e6, 3e12, 1, null, 1, 1],
    ["MU", "Micron Technology Inc. Common Stock", 100, 0, 0, 1e6, 1e11, 1, null, 1, 1],
  ],
  sectors: ["", "Technology", "Real Estate"], industries: ["", "x", "y"], countries: ["", "United States"],
  count: 4, as_of_text: "Data as of Oct 16, 2026 4:15 PM ET", market: "us", source: "nasdaq_screener", as_of: now(),
};
const listing = (figi: string, exch: string) => ({
  figi, composite_figi: "BBG000B9XRY4", share_class_figi: "BBG001S5N8V8", ticker: "AAPL", name: "APPLE INC", exch_code: exch,
  security_type: "Common Stock", market_sector: "Equity", description: "AAPL",
});
const FIGI = {
  items: [
    { kind: "ISIN", id: "US0378331005", status: "FOUND", message: null, listings: [listing("BBG000B9XRY4", "US"), listing("BBG000B9XSK7", "ZZ")] },
    { kind: "ISIN", id: "US0000000002", status: "NOT FOUND", message: "No identifier found.", listings: [] },
  ],
  note: "OPENFIGI: IDENTIFIER MAPPING, NOT A PRICE SOURCE. EXCHANGE CODES ARE OPENFIGI'S OWN.",
};

async function setupSecf(page: Page) {
  const base = await setup(page);
  const calls = { search: [] as string[], figi: [] as string[] };
  await page.route("**/api/screener", (r) => r.fulfill({ json: env(UNIVERSE, { source: "nasdaq_screener" }) }));
  await page.route("**/api/search?**", (r) => {
    calls.search.push(new URL(r.request().url()).searchParams.get("q")!);
    return r.fulfill({ json: env([{ symbol: "RELIANCE.NS", name: "Reliance Industries Limited", exchange: "NSI", type: "EQUITY", source: "yahoo" }]) });
  });
  const nav = { query: "", items: [], total: 0, shown: 0, nav_date: "2026-10-16", schemes: 186, note: "AMFI NAV" };
  await page.route("**/api/world/mfnav?**", (r) => r.fulfill({ json: env(nav, { source: "amfi" }) }));
  await page.route("**/api/world/figi?**", (r) => {
    calls.figi.push(new URL(r.request().url()).searchParams.get("q")!);
    return r.fulfill({ json: env(FIGI, { source: "openfigi" }) });
  });
  return { ...base, calls };
}

test("SECF: a typo still finds the name, results come from the universe and the Yahoo search, Enter opens DES", async ({ page }) => {
  const { errors, calls } = await setupSecf(page);
  await run(page, "SECF microsft");
  const p = panel(page);
  await expect(p).toContainText("SECF MICROSFT");
  await expect(p).toContainText("NAME SEARCH");
  await expect(p).toContainText("1 MATCH");
  await expect(p.locator(".sr")).toContainText("MSFT");
  expect(calls.search).toContain("microsft"); // (the command line also searches while you type)
  expect(calls.figi).toEqual([]);

  await run(page, "SECF apple");
  await expect(p).toContainText("2 MATCH");
  await expect(p.locator(".sr")).toContainText("AAPL"); // larger market cap first
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("APLE");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("DES");
  expect(errors).toEqual([]);
});

test("SECF: a Yahoo-only name (not in the US universe) is found and labelled SEARCH", async ({ page }) => {
  await setupSecf(page);
  await run(page, "SECF reliance");
  await expect(panel(page)).toContainText("1 MATCH");
  await expect(panel(page).locator(".sr")).toContainText("RELIANCE.NS");
  await expect(panel(page).locator(".sr")).toContainText("SEARCH");
});

test("SECF: an ISIN is mapped by OpenFIGI, unknown ones say NOT FOUND, Enter opens a mapped listing and explains an unmapped one", async ({ page }) => {
  const { errors, calls } = await setupSecf(page);
  await run(page, "SECF US0378331005 US0000000002");
  const p = panel(page);
  await expect(p).toContainText("IDENTIFIER LOOKUP");
  await expect(p).toContainText("OPENFIGI");
  await expect(p).toContainText("3 LINES");
  await expect(p).toContainText("NOT A PRICE SOURCE");
  await expect(p.locator(".sr")).toContainText("US0378331005");
  await expect(p.locator(".sr")).toContainText("BBG000B9XRY4");
  expect(calls.figi).toEqual(["US0378331005 US0000000002"]);
  expect(calls.search).not.toContain("US0378331005 US0000000002");

  await page.keyboard.press("j"); // a listing on an exchange code OpenTerm has no mapping for
  await expect(p.locator(".sr")).toContainText("BBG000B9XSK7");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("NO OPENTERM SYMBOL FOR OPENFIGI EXCHANGE CODE ZZ");
  await page.keyboard.press("j"); // the not-found line has no listing
  await expect(p.locator(".sr")).toContainText("NOT FOUND");
  await page.keyboard.press("k");
  await page.keyboard.press("k");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("DES");
  expect(errors).toEqual([]);
});

test("SECF: a bad identifier or a failing OpenFIGI is said plainly", async ({ page }) => {
  await setupSecf(page);
  await page.route("**/api/world/figi?**", (r) =>
    r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "openfigi: rate_limited (429 from upstream)" } }),
  );
  await run(page, "SECF US0378331005");
  await expect(panel(page)).toContainText("OPENFIGI: PROVIDER DOWN");
  await expect(panel(page)).toContainText("rate_limited");
  await run(page, "SECF");
  await expect(panel(page)).toContainText("TYPE A NAME, A TICKER OR AN IDENTIFIER");
  await run(page, "SECF zzzzqq");
  await expect(panel(page)).toContainText("NOTHING MATCHES ZZZZQQ");
});
