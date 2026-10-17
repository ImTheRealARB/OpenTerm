import { expect, test, type Page, type Route } from "@playwright/test";

const now = () => Date.now() / 1000;
const env = (data: unknown, extra = {}) => ({ data, source: "fred_csv", as_of: now(), age_s: 2, stale: false, fallback_from: [], ...extra });
const err = (r: Route, status: number, error: string, kind: string, detail?: string) => r.fulfill({ status, json: { error, kind, detail } });

/** Monthly observations ending 2026-09-01 (UTC midnight epoch seconds). */
function series(id: string, values: (number | null)[], extra = {}) {
  const end = Date.UTC(2026, 8, 1) / 1000;
  const t = values.map((_, i) => Math.round(end - (values.length - 1 - i) * 30.4375 * 86400));
  const last = values[values.length - 1] as number;
  const prev = values[values.length - 2] as number;
  return {
    id, title: "Unemployment Rate", units: "Percent", frequency: "Monthly", seasonal_adjustment: "SA", last_updated: null,
    meta_source: "curated", t, v: values, last_value: last, last_date: "2026-09-01", prev_value: prev, change: last - prev,
    missing: values.filter((v) => v == null).length, source: "fred_csv", as_of: now(), range: "5Y", key_set: false, ...extra,
  };
}
const UNRATE = Array.from({ length: 60 }, (_, i) => (i === 40 ? null : 3.5 + (i % 7) * 0.1)).slice(0, 58).concat([4.1, 4.2]);

const macroRow = (id: string, label: string, last: number, change: number, extra = {}) => ({
  id, label, title: `${label} (full title)`, units: "Percent", frequency: "Monthly", last_value: last, last_date: "2026-09-01",
  prev_value: last - change, change, source: "fred_csv", age_s: 3, stale: false, ...extra,
});

const TENORS = ["1M", "1.5M", "3M", "2Y", "10Y", "30Y"];
const CURVE = {
  date: "2026-10-16", tenors: TENORS, years: [1 / 12, 0.125, 0.25, 2, 10, 30], yields: [4.2, 4.2, 4.15, 4.35, 4.7, 5.0],
  spread_2s10s: 0.35,
  compare: {
    "1D": { date: "2026-10-15", yields: [4.17, 4.18, 4.15, 4.28, 4.62, 4.95], spread_2s10s: 0.34 },
    "1W": { date: "2026-10-09", yields: [4.13, 4.13, 4.13, 4.4, 4.8, 5.1], spread_2s10s: 0.4 },
    "1M": { date: "2026-09-16", yields: [3.96, 4.0, 4.07, 4.14, 4.24, 4.9], spread_2s10s: 0.1 },
    "1Y": { date: "2025-10-16", yields: [4.2, 4.17, 4.1, 3.96, 3.54, 4.6], spread_2s10s: -0.42 },
  },
  note: null, source: "treasury", as_of: now(),
};

const earning = (symbol: string, name: string, cap: number, extra = {}) => ({
  symbol, name, time: "PRE", fiscal_quarter: "Sep/2026", eps_forecast: 1.25, n_ests: 7, last_year_eps: 1.1, last_year_date: "10/15/2025",
  eps: null, surprise_pct: null, market_cap: cap, ...extra,
});

const ev = (date: string, time: string | null, name: string, agency: string, major = false) => ({
  date, time, ts: Date.parse(`${date}T${time ?? "00:00"}:00-04:00`) / 1000, name, agency, major, source: "agency_ics",
});
const ECO = {
  start: "2026-10-17", days: 14, failed: [], coverage_end: "2027-12-22", key_set: false,
  events: [
    ev("2026-10-20", "10:00", "State Employment and Unemployment (Monthly)", "BLS"),
    ev("2026-10-21", "08:30", "Consumer Price Index", "BLS", true),
    ev("2026-10-21", "10:00", "Usual Weekly Earnings of Wage and Salary Workers", "BLS"),
    ev("2026-10-29", "08:30", "Gross Domestic Product", "BEA", true),
  ],
};

async function setup(page: Page) {
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => r.fulfill({ json: { results: {} } }));
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
/** The canvas grid mirrors its selected row into a visually hidden live region. */
const selected = (page: Page, id = 1) => panel(page, id).locator(".grid .sr");
const queries = (log: string[]) => log.map((u) => new URL(u, "http://x").search);

test("FRED: plots a series with title, units, last value, source and age; digits pick the range", async ({ page }) => {
  await setup(page);
  const seen: string[] = [];
  await page.route("**/api/fred?**", (r) => {
    seen.push(r.request().url());
    const q = new URL(r.request().url()).searchParams;
    return r.fulfill({ json: env(series(q.get("id")!, UNRATE, { range: q.get("range") })) });
  });
  await run(page, "FRED unrate 10y");
  const p = panel(page);
  await expect(p.locator(".ph")).toContainText("FRED");
  await expect(p).toContainText("UNRATE UNEMPLOYMENT RATE");
  await expect(p).toContainText("PERCENT");
  await expect(p).toContainText("MONTHLY SA");
  await expect(p).toContainText("LAST 4.20 (2026-09-01)");
  await expect(p).toContainText("+0.10 VS PRIOR OBS");
  await expect(p).toContainText("1 MISSING OBS SKIPPED");
  await expect(p).toContainText("FRED_CSV");
  await expect(p).toContainText("AGE 2S");
  await expect(p.locator(".chart canvas").first()).toBeVisible();
  expect(queries(seen)[0]).toBe("?id=UNRATE&range=10Y");

  await page.keyboard.press("1");
  await expect(p).toContainText("UNRATE UNEMPLOYMENT RATE · 1Y");
  await expect.poll(() => queries(seen).at(-1)).toBe("?id=UNRATE&range=1Y");
  await page.keyboard.press("x"); // crosshair readout uses the series units, not O/H/L/C
  await expect(p).toContainText("CROSSHAIR");
  await expect(p.locator(".chart").locator("xpath=..").locator(".line").first()).toContainText("PERCENT");
});

test("FRED: keyless series without metadata says so; no id shows usage; unknown id and outage are explicit", async ({ page }) => {
  await setup(page);
  await page.route("**/api/fred?**", (r) => {
    const id = new URL(r.request().url()).searchParams.get("id")!;
    if (id === "NOPE1") return err(r, 404, "NO FRED SERIES NOPE1", "not_found", "fred_csv: not_found (404)");
    if (id === "DOWN1") return err(r, 503, "PROVIDER DOWN", "unavailable", "fred_csv: unavailable (timeout)");
    return r.fulfill({ json: env(series(id, UNRATE, { title: null, units: null, frequency: null, seasonal_adjustment: null, meta_source: "none" })) });
  });
  await run(page, "FRED DGS10");
  const p = panel(page);
  await expect(p).toContainText("NO TITLE OR UNITS FROM THE KEYLESS SOURCE");
  await expect(p.locator(".chart canvas").first()).toBeVisible();

  await run(page, "FRED");
  await expect(p).toContainText("USAGE: FRED SERIES_ID");

  await run(page, "FRED nope1");
  await expect(p).toContainText("NO FRED SERIES NOPE1");
  await expect(p).toContainText("fred_csv: not_found (404)");
  await expect(p).toContainText("TRY MACRO");

  await run(page, "FRED down1");
  await expect(p).toContainText("PROVIDER DOWN: PROVIDER DOWN");
  await expect(p).toContainText("fred_csv: unavailable (timeout)");
});

test("MACRO without a key: built-in list, a clear needs-key notice, Enter plots the series", async ({ page }) => {
  await setup(page);
  const seen: string[] = [];
  await page.route("**/api/macro?**", (r) => {
    seen.push(r.request().url());
    return r.fulfill({
      json: env({
        mode: "curated", query: null, needs_key: "FRED_API_KEY",
        rows: [macroRow("GDP", "GDP", 32563.03, 656.756), macroRow("UNRATE", "Unemployment rate", 4.2, 0.1), macroRow("BADID", "Broken", 0, 0, { error: "fred_csv: unavailable (timeout)" })],
      }),
    });
  });
  const fredSeen: string[] = [];
  await page.route("**/api/fred?**", (r) => {
    fredSeen.push(r.request().url());
    return r.fulfill({ json: env(series("UNRATE", UNRATE)) });
  });
  await run(page, "MACRO");
  const p = panel(page);
  await expect(p).toContainText("COMMON FRED SERIES");
  await expect(p).toContainText("3 SERIES");
  await expect(p).toContainText("SEARCH OF ALL FRED NEEDS FRED_API_KEY");
  await expect(p).toContainText("FRED_CSV");
  await expect(selected(page)).toContainText("GDP");
  await expect(selected(page)).toContainText("32,563.0");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("UNRATE");
  await expect(selected(page)).toContainText("+0.10");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("ERR");
  await expect(selected(page)).toContainText("fred_csv: unavailable (timeout)");
  await page.keyboard.press("k");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("FRED");
  await expect(p).toContainText("UNRATE UNEMPLOYMENT RATE");
  expect(queries(fredSeen)[0]).toBe("?id=UNRATE&range=5Y");
  expect(queries(seen)[0]).toBe("");
});

test("MACRO with a key searches FRED; a query with no match in the keyless list says so", async ({ page }) => {
  await setup(page);
  await page.route("**/api/macro?**", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q");
    if (q === "inflation") {
      return r.fulfill({
        json: env({
          mode: "search", query: "inflation", needs_key: null,
          rows: [{ id: "T10YIE", title: "10-Year Breakeven Inflation Rate", units: "%", frequency: "D", observation_end: "2026-10-15" }],
        }, { source: "fred" }),
      });
    }
    return r.fulfill({ json: env({ mode: "curated", query: q, needs_key: "FRED_API_KEY", rows: [] }) });
  });
  await run(page, "MACRO inflation");
  const p = panel(page);
  await expect(p).toContainText('FRED SEARCH "inflation"');
  await expect(selected(page)).toContainText("T10YIE");
  await expect(selected(page)).toContainText("10-Year Breakeven Inflation Rate");
  await expect(p).not.toContainText("NEEDS FRED_API_KEY");

  await run(page, "MACRO zzzz");
  await expect(p).toContainText('NO BUILT-IN SERIES MATCH "ZZZZ"');
  await expect(p).toContainText("SEARCH OF ALL FRED NEEDS FRED_API_KEY");
});

test("RATES: curve with bp changes and spreads; Enter plots the FRED series; tenors without one say so", async ({ page }) => {
  await setup(page);
  await page.route("**/api/rates", (r) => r.fulfill({ json: env(CURVE, { source: "treasury" }) }));
  const fredSeen: string[] = [];
  await page.route("**/api/fred?**", (r) => {
    fredSeen.push(r.request().url());
    return r.fulfill({ json: env(series("DGS10", UNRATE)) });
  });
  await run(page, "RATES");
  const p = panel(page);
  await expect(p).toContainText("US TREASURY PAR YIELD CURVE · 2026-10-16");
  await expect(p).toContainText("TREASURY");
  await expect(p).toContainText("2Y10Y +35 BP NORMAL");
  await expect(p).toContainText("3M10Y");
  await expect(p).toContainText("1Y +77"); // 2s10s: 35 bp now vs -42 bp a year ago
  await expect(selected(page)).toContainText("1M");
  await expect(selected(page)).toContainText("4.20");
  await page.keyboard.press("j");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("FRED HAS NO DAILY SERIES FOR THE 1.5M TENOR");
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("10Y");
  await expect(selected(page)).toContainText("+8"); // 4.70 vs 4.62 yesterday
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("FRED");
  await expect.poll(() => queries(fredSeen)[0]).toBe("?id=DGS10&range=5Y");
});

test("RATES: fallback to FRED is flagged; an outage is PROVIDER DOWN", async ({ page }) => {
  await setup(page);
  let down = false;
  await page.route("**/api/rates", (r) =>
    down
      ? err(r, 503, "PROVIDER DOWN", "unavailable", "treasury: unavailable (503); fred_csv: unavailable (timeout)")
      : r.fulfill({ json: env({ ...CURVE, source: "fred_csv" }, { source: "fred_csv", fallback_from: ["treasury"] }) }),
  );
  await run(page, "RATES");
  const p = panel(page);
  await expect(p).toContainText("TREASURY DOWN, VIA FALLBACK");
  await expect(p).toContainText("TREASURY.GOV DID NOT ANSWER");
  down = true;
  await page.keyboard.press("F5");
  await expect(p).toContainText("PROVIDER DOWN: PROVIDER DOWN");
  await expect(p).toContainText("treasury: unavailable (503)");
  await expect(p).toContainText("SHOWING STALE DATA");
});

test("ERN: a reported day, day navigation, weekend message, Enter opens DES", async ({ page }) => {
  await setup(page);
  const seen: string[] = [];
  await page.route("**/api/earnings?**", (r) => {
    const d = new URL(r.request().url()).searchParams.get("date")!;
    seen.push(d);
    const rows =
      d === "2026-10-16"
        ? [earning("JPM", "JPMorgan Chase & Co.", 8.2e11, { eps_forecast: 4.8, eps: 5.07, surprise_pct: 5.6 }), earning("ABT", "Abbott Laboratories", 2.1e11, { time: "POST", eps: 1.2, surprise_pct: -2.4 })]
        : [];
    return r.fulfill({ json: env({ date: d, as_of_text: "Fri, Oct 16, 2026", rows, source: "nasdaq_earnings", as_of: now() }, { source: "nasdaq_earnings" }) });
  });
  await run(page, "ERN 2026-10-16");
  const p = panel(page);
  await expect(p).toContainText("EARNINGS · FRI 16 OCT 2026 · 2 REPORTS · 2 REPORTED");
  await expect(p).toContainText("NASDAQ_EARNINGS");
  await expect(selected(page)).toContainText("JPM");
  await expect(selected(page)).toContainText("+5.60%");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("ABT");
  await expect(selected(page)).toContainText("POST");
  await expect(selected(page)).toContainText("-2.40%");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("ABT | DES");

  await run(page, "ERN 2026-10-16");
  await page.keyboard.press("ArrowRight");
  await expect(p).toContainText("SAT 17 OCT 2026");
  await expect(p).toContainText("NASDAQ LISTS NO REPORTS FOR 2026-10-17 (WEEKEND)");
  expect(seen).toContain("2026-10-17");
  await page.keyboard.press("ArrowLeft");
  await expect(p).toContainText("FRI 16 OCT 2026");
});

test("ERN: bad date and upstream error are explicit", async ({ page }) => {
  await setup(page);
  await page.route("**/api/earnings?**", (r) => err(r, 503, "PROVIDER DOWN", "unavailable", "nasdaq_earnings: unavailable (timeout)"));
  await run(page, "ERN next");
  const p = panel(page);
  await expect(p).toContainText("BAD DATE NEXT");
  await run(page, "ERN +1");
  await expect(p).toContainText("PROVIDER DOWN: PROVIDER DOWN");
  await expect(p).toContainText("nasdaq_earnings: unavailable (timeout)");
});

test("ECO: release schedule with major flags, window and start shifting, MAJOR filter", async ({ page }) => {
  await setup(page);
  const seen: string[] = [];
  await page.route("**/api/eco?**", (r) => {
    seen.push(r.request().url());
    return r.fulfill({ json: env(ECO, { source: "agency_ics" }) });
  });
  await run(page, "ECO");
  const p = panel(page);
  await expect(p).toContainText("ECONOMIC CALENDAR · 2026-10-17 TO 2026-10-30 (14D)");
  await expect(p).toContainText("4 RELEASES");
  await expect(p).toContainText("BLS AND BEA OFFICIAL SCHEDULES");
  await expect(p).toContainText("NO FORECASTS OR ACTUALS");
  await expect(selected(page)).toContainText("TUE 20 OCT 2026");
  await expect(selected(page)).toContainText("State Employment and Unemployment");
  await page.keyboard.press("j");
  await expect(selected(page)).toContainText("MAJOR");
  await expect(selected(page)).toContainText("Consumer Price Index");
  await expect(selected(page)).toContainText("08:30");
  expect(queries(seen)[0]).toBe("?days=14");

  await page.keyboard.press("m");
  await expect(p).toContainText("MAJOR ONLY");
  await expect(p).toContainText("2 RELEASES");
  await page.keyboard.press("1");
  await expect.poll(() => queries(seen).at(-1)).toBe("?days=7");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => queries(seen).at(-1)).toMatch(/^\?start=\d{4}-\d{2}-\d{2}&days=7$/);
});

test("ECO: a failed agency feed and an empty window are said out loud", async ({ page }) => {
  await setup(page);
  await page.route("**/api/eco?**", (r) =>
    r.fulfill({ json: env({ ...ECO, events: [], failed: ["BLS"], coverage_end: "2026-12-18" }, { source: "agency_ics" }) }),
  );
  await run(page, "ECO 30");
  const p = panel(page);
  await expect(p).toContainText("BLS FEED DID NOT ANSWER");
  await expect(p).toContainText("NO RELEASES IN THIS WINDOW");
  await run(page, "ECO zzz");
  await expect(p).toContainText("BAD ARGUMENT ZZZ");
});

test("every Phase 7 function is listed as ready in HELP", async ({ page }) => {
  await setup(page);
  await run(page, "HELP");
  for (const code of ["ECO", "MACRO", "FRED", "RATES", "ERN"]) {
    const row = panel(page).locator("tr").filter({ has: page.locator("td.acc", { hasText: new RegExp(`^${code}$`) }) });
    await expect(row).toContainText("READY");
  }
});
