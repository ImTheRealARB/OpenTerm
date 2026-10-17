import { expect, test, type Page } from "@playwright/test";

// All payloads below are test data served by mocked routes; nothing here reaches the network.
const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "sec", as_of: now(), age_s: 1, stale: false, fallback_from: [], ...extra });

const period = (label: string, end: string, derived = false) => ({
  key: label, label, end, start: null, fy: 2025, fp: derived ? "Q4" : "FY", form: "10-K", filed: "2025-10-31", derived,
});
const row = (key: string, label: string, unit: string, values: (number | null)[], flags: string[], computed = false) => ({
  key, label, unit, values, flags, tags: values.map(() => (computed ? null : "Revenues")), computed,
});
const FA = (p: "A" | "Q") => ({
  symbol: "AAPL", cik: 320193, name: "Apple Inc.", currency: "USD", period: p, source: "sec",
  periods: p === "A" ? [period("FY2025", "2025-09-27"), period("FY2024", "2024-09-28"), period("FY2023", "2023-09-30")]
    : [period("Q4 FY25", "2025-09-27", true), period("Q3 FY25", "2025-06-28"), period("Q2 FY25", "2025-03-29")],
  statements: {
    IS: [
      row("revenue", "Revenue", "USD", p === "A" ? [416e9, 391e9, 383e9] : [102e9, 94e9, 95e9], p === "A" ? ["", "", ""] : ["d", "", ""]),
      row("eps_diluted", "EPS (diluted)", "USD/shares", [7.46, 6.08, 6.13], ["", "", ""]),
    ],
    BS: [row("assets", "Total assets", "USD", [359e9, 365e9, 352e9], ["", "", ""])],
    CF: [row("fcf", "Free cash flow", "USD", [-5e6, 108e9, 99e9], ["c", "c", "c"], true)],
  },
});
const filing = (form: string, filed: string, accession: string, description: string) => ({
  accession, filed, report_date: filed, form, description, items: form === "8-K" ? "2.02,9.01" : null, primary_doc: "d.htm",
  url: `https://www.sec.gov/Archives/edgar/data/320193/${accession.replaceAll("-", "")}/`,
  doc_url: `https://www.sec.gov/Archives/edgar/data/320193/${accession.replaceAll("-", "")}/d.htm`,
});
const FILINGS = [
  filing("8-K", "2026-08-01", "0000320193-26-000010", "Results of operations"),
  filing("10-Q", "2026-05-02", "0000320193-26-000008", "Quarterly report"),
  filing("10-K", "2025-10-31", "0000320193-25-000079", "Annual report"),
];
const trade = (owner: string, code: string, code_text: string, shares: number, price: number | null, acq: "A" | "D", date: string) => ({
  owner, owner_cik: null, relation: "Officer", date, code, code_text, acq_disp: acq, shares, price,
  value: price ? shares * price : null, owned_after: 1_000_000, direct: "D", security: "Common Stock", derivative: false,
  accession: "0000000000-26-000001", filed: date, url: "https://www.sec.gov/Archives/edgar/data/320193/f4/",
});
const INSIDERS = {
  symbol: "AAPL", cik: 320193, name: "Apple Inc.", filings_read: 20, failed: ["0000000000-26-000099"], source: "sec",
  trades: [
    trade("Doe Jane", "S", "Open-market sale", 10_000, 200, "D", "2026-08-05"),
    trade("Roe Rick", "A", "Grant or award", 5_000, null, "A", "2026-08-03"),
    trade("Poe Pat", "P", "Open-market purchase", 1_000, 190, "A", "2026-08-02"),
  ],
};
const holder = (name: string, pct: number, shares: number) => ({ holder: name, pct_held: pct, shares, value: shares * 200, pct_change: -0.01, report_date: "2026-06-30" });
const HOLDERS = {
  symbol: "AAPL",
  breakdown: { insiders_pct: 0.0165, institutions_pct: 0.65, institutions_float_pct: 0.66, institutions_count: 7000 },
  institutions: [holder("Vanguard Group Inc", 0.0966, 1_400_000_000), holder("Blackrock Inc.", 0.0797, 1_160_000_000)],
  funds: [holder("Vanguard Total Stock Market Index", 0.03, 440_000_000)],
  source: "yahoo_own",
};
const SEC_403 = {
  status: 503,
  json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "sec: unavailable (403 from SEC: set SEC_USER_AGENT in .env, e.g. 'Your Name you@example.com')" },
};

const asked: string[] = [];

async function setup(page: Page) {
  asked.length = 0;
  await page.routeWebSocket(/\/ws$/, (route) =>
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    }),
  );
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    const q = (s: string) => ({ symbol: s, name: s, currency: "USD", exchange: "X", tz: "America/New_York", price: 100, prev_close: 99, change: 1, change_pct: 1, open: null, high: 101, low: 98, volume: 1, high_52w: null, low_52w: null, market_time: Math.floor(now()), source: "yahoo", as_of: now() });
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s) => [s, env(q(s), { source: "yahoo" })])) } });
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
  await page.keyboard.press("Escape"); // leave the command line: letters go to the panel
};
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const selected = (page: Page, id = 1) => panel(page, id).locator(".grid .sr");

test("FA: annual income statement, statements and A/Q keys, derived quarter marker, US-only and stale states", async ({ page }) => {
  await setup(page);
  let stale = false;
  await page.route("**/api/fa?**", (r) => {
    const u = new URL(r.request().url());
    asked.push(u.search);
    if (u.searchParams.get("symbol") === "RELIANCE.NS")
      return r.fulfill({ status: 404, json: { error: "SEC DATA COVERS US FILERS ONLY", kind: "not_found", detail: "RELIANCE.NS: not an SEC filer" } });
    return r.fulfill({ json: env(FA(u.searchParams.get("period") as "A" | "Q"), stale ? { stale: true, age_s: 7200 } : {}) });
  });
  await run(page, "AAPL FA");
  const p = panel(page);
  await expect(p).toContainText("FA AAPL · APPLE INC.");
  await expect(p).toContainText("SEC EDGAR");
  await expect(p).toContainText("ANNUAL");
  await expect(p).toContainText("USD MILLIONS");
  await expect(selected(page)).toContainText("Revenue");
  await expect(selected(page)).toContainText("FY2025 416,000");
  await expect(selected(page)).toContainText("FY2024 391,000");
  expect(asked[0]).toBe("?symbol=AAPL&period=A");

  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("EPS (diluted)");
  await expect(selected(page)).toContainText("FY2025 7.46");
  await page.keyboard.press("h"); // scroll to older periods: the newest column drops off
  await expect(selected(page)).toContainText("FY2024 6.08");
  await expect(selected(page)).not.toContainText("FY2025");
  await page.keyboard.press("l");

  await page.keyboard.press("2");
  await expect(selected(page)).toContainText("Total assets");
  await page.keyboard.press("3");
  await expect(selected(page)).toContainText("Free cash flow");
  await expect(selected(page)).toContainText("FY2025 -5.0");

  await page.keyboard.press("1");
  await page.keyboard.press("q");
  await expect(p).toContainText("QUARTERLY");
  await expect(selected(page)).toContainText("Q4 FY25 102,000*");
  await expect(p.locator(".summary")).toContainText("* DERIVED");
  expect(asked.at(-1)).toBe("?symbol=AAPL&period=Q");

  stale = true;
  await page.keyboard.press("F5");
  await expect(p).toContainText("STALE 2H");

  await run(page, "RELIANCE.NS FA");
  await expect(panel(page)).toContainText("SEC DATA COVERS US FILERS ONLY");
});

test("FIL: filings list, form filter key, Enter opens the document, SEC alias, SEC_USER_AGENT hint on 403", async ({ page }) => {
  await setup(page);
  await page.route("**/api/filings?**", (r) => {
    const u = new URL(r.request().url());
    asked.push(u.search);
    if (u.searchParams.get("symbol") === "MSFT") return r.fulfill(SEC_403);
    const form = u.searchParams.get("form");
    const list = form ? FILINGS.filter((f) => f.form === form) : FILINGS;
    return r.fulfill({ json: env({ symbol: "AAPL", cik: 320193, name: "Apple Inc.", fiscal_year_end: "0926", sic: "3571", form: form || null, total: list.length, filings: list, source: "sec" }) });
  });
  await run(page, "AAPL FIL");
  const p = panel(page);
  await expect(p).toContainText("FIL AAPL · APPLE INC.");
  await expect(p).toContainText("3 OF 3 FILINGS");
  await expect(selected(page)).toContainText("8-K");
  await expect(selected(page)).toContainText("Results of operations");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("Quarterly report");

  await page.keyboard.press("3"); // 10-Q
  await expect.poll(() => asked.at(-1)).toBe("?symbol=AAPL&form=10-Q");
  await expect(p).toContainText("1 OF 1 FILINGS");
  await expect(selected(page)).toContainText("0000320193-26-000008");

  // The document opens on sec.gov in a new tab; answer it locally so the test never touches the network.
  await page.context().route("https://www.sec.gov/**", (r) => r.fulfill({ body: "filing" }));
  const tab = page.context().waitForEvent("page");
  await page.keyboard.press("Enter");
  expect((await tab).url()).toBe("https://www.sec.gov/Archives/edgar/data/320193/000032019326000008/d.htm");

  await page.bringToFront();
  await run(page, "AAPL SEC 10-K");
  await expect.poll(() => asked.at(-1)).toBe("?symbol=AAPL&form=10-K");
  await expect(selected(page)).toContainText("Annual report");

  await run(page, "MSFT FIL");
  await expect(p).toContainText("PROVIDER DOWN");
  await expect(p).toContainText("403 from SEC");
  await expect(p).toContainText("SET SEC_USER_AGENT");
});

test("OWN: Form 4 trades, totals, open-market filter, unread filings are reported", async ({ page }) => {
  await setup(page);
  await page.route("**/api/insiders?**", (r) => r.fulfill({ json: env(INSIDERS) }));
  await run(page, "AAPL OWN");
  const p = panel(page);
  await expect(p).toContainText("OWN AAPL · APPLE INC.");
  await expect(p).toContainText("SEC EDGAR");
  await expect(p).toContainText("3 TRADES");
  await expect(p).toContainText("BOUGHT 190.0K");
  await expect(p).toContainText("SOLD 2.00M");
  await expect(p).toContainText("20 FORM 4S READ");
  await expect(p).toContainText("1 FORM 4 NOT READ");
  await expect(selected(page)).toContainText("Doe Jane");
  await expect(selected(page)).toContainText("Open-market sale");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("Grant or award");
  await expect(selected(page)).toContainText("PRICE —");

  await page.keyboard.press("m");
  await expect(p).toContainText("2 TRADES (OPEN MARKET)");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("Poe Pat");
  await page.keyboard.press("m");
  await expect(p).toContainText("3 TRADES");
});

test("OWN: empty result and a failed provider say so", async ({ page }) => {
  await setup(page);
  await page.route("**/api/insiders?**", (r) => {
    if (new URL(r.request().url()).searchParams.get("symbol") === "MSFT") return r.fulfill(SEC_403);
    return r.fulfill({ json: env({ ...INSIDERS, trades: [], failed: [], filings_read: 0 }) });
  });
  await run(page, "AAPL OWN");
  await expect(panel(page)).toContainText("NO INSIDER TRADES REPORTED FOR AAPL");
  await run(page, "MSFT OWN");
  await expect(panel(page)).toContainText("PROVIDER DOWN");
  await expect(panel(page)).toContainText("SET SEC_USER_AGENT");
});

test("HDS: breakdown, institutions and funds; cursor skips section headers; yahoo source and stale shown", async ({ page }) => {
  await setup(page);
  await page.route("**/api/holders?**", (r) => r.fulfill({ json: env(HOLDERS, { source: "yahoo_own", stale: true, age_s: 600 }) }));
  await run(page, "AAPL HDS");
  const p = panel(page);
  await expect(p).toContainText("HDS AAPL");
  await expect(p).toContainText("YAHOO FINANCE");
  await expect(p).toContainText("STALE 10M");
  await expect(p).toContainText("2 INSTITUTIONS · 1 FUNDS");
  await expect(selected(page)).toContainText("Insiders"); // the cursor starts under the MAJOR HOLDERS header
  await expect(selected(page)).toContainText("1.65%");
  for (let i = 0; i < 4; i++) await page.keyboard.press("j"); // past three summary rows and the TOP INSTITUTIONS header
  await expect(selected(page)).toContainText("Vanguard Group Inc");
  await expect(selected(page)).toContainText("9.66%");
  await expect(selected(page)).toContainText("-1.00%");
  await page.keyboard.press("j");
  await page.keyboard.press("j"); // skips the TOP FUNDS header
  await expect(selected(page)).toContainText("Vanguard Total Stock Market Index");
});

test("HDS: provider failure shows the error with its cause", async ({ page }) => {
  await setup(page);
  await page.route("**/api/holders?**", (r) =>
    r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "yahoo_own: rate_limited (429 from upstream)" } }),
  );
  await run(page, "AAPL HDS");
  await expect(panel(page)).toContainText("PROVIDER DOWN");
  await expect(panel(page)).toContainText("yahoo_own: rate_limited");
});

test("FA: E and Alt+X export the statement shown (CSV hook)", async ({ page }) => {
  await setup(page);
  await page.route("**/api/fa?**", (r) => r.fulfill({ json: env(FA(new URL(r.request().url()).searchParams.get("period") as "A" | "Q")) }));
  await run(page, "AAPL FA");
  await expect(selected(page)).toContainText("FY2025 416,000");
  for (const press of ["e", "Alt+x"]) {
    const [dl] = await Promise.all([page.waitForEvent("download"), page.keyboard.press(press)]);
    expect(dl.suggestedFilename()).toMatch(/^FA_AAPL_IS_A.*\.csv$/);
    const text = (await (await dl.createReadStream()).toArray()).join("");
    expect(text).toContain("LINE,FY2025,FY2024,FY2023");
    expect(text).toContain("Revenue");
  }
});
