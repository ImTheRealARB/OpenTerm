import { expect, test } from "@playwright/test";
import { env, exportCsv, panel, run, setup } from "./p19util";

// MF end-to-end tests (mocked routes only, no network). The funds and NAVs below are MADE-UP test data in the shape the backend returns
// (the real shapes are recorded in backend/tests/fixtures/mfapi_real_*.json); none of it is a real fund's number.

const SOURCE_NOTE = "MFAPI.IN IS A FREE COMMUNITY SERVICE THAT REPUBLISHES AMFI'S DAILY NAV. IT IS NOT AN OFFICIAL AMFI API AND MAY LAG A DAY.";
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);

const SEARCH = {
  mode: "SEARCH", query: "test fund", total: 2, shown: 2, source_note: SOURCE_NOTE,
  note: "ENTER OPENS THE FUND. EVERY WORD MUST APPEAR IN THE SCHEME NAME (ANY ORDER). DIRECT AND REGULAR PLANS ARE SEPARATE SCHEMES.",
  items: [{ code: 900001, name: "Test Fund - Direct Plan - Growth" }, { code: 900002, name: "Test Fund - Regular Plan - Growth" }],
};

/** A fund with 60 daily NAVs ending `lagDays` ago, so 1D and 1W have numbers and the longer periods are dashes. */
function fund(code: number, lagDays = 1) {
  const n = 60;
  const t = Array.from({ length: n }, (_, i) => Math.floor(Date.parse(iso(lagDays + n - 1 - i)) / 1000));
  const v = Array.from({ length: n }, (_, i) => 100 + i * 0.1);
  const row = (period: string, kind: string, pct: number | null, why: string | null) => ({
    period, kind, target: iso(lagDays + 1), base_date: pct == null ? null : iso(lagDays + 1), base_nav: pct == null ? null : 105.8, pct, why,
  });
  return {
    mode: "FUND", code, name: `Test Fund ${code} - Direct Plan - Growth`, fund_house: "TEST MUTUAL FUND", scheme_type: "Open Ended Schemes",
    category: "Equity Scheme - Flexi Cap Fund", isin_growth: "INF000TEST01", isin_div: null,
    latest: { date: iso(lagDays), nav: v[n - 1] }, first_date: iso(lagDays + n - 1), points: n, t, v, payout_plan: false, source_note: SOURCE_NOTE,
    note: "NAV IS AN END-OF-DAY VALUE PER UNIT, NOT A MARKET PRICE. HISTORICAL, NOT A FORECAST. UP TO 1Y = ABSOLUTE RETURN; OVER 1Y = CAGR.",
    returns: [
      row("1D", "ABSOLUTE RETURN", 0.0945, null), row("1W", "ABSOLUTE RETURN", 0.66, null), row("1M", "ABSOLUTE RETURN", 2.9, null),
      row("3M", "ABSOLUTE RETURN", null, `HISTORY STARTS ${iso(lagDays + n - 1)}`), row("6M", "ABSOLUTE RETURN", null, `HISTORY STARTS ${iso(lagDays + n - 1)}`),
      row("1Y", "ABSOLUTE RETURN", null, `HISTORY STARTS ${iso(lagDays + n - 1)}`), row("3Y", "CAGR", null, `HISTORY STARTS ${iso(lagDays + n - 1)}`),
      row("5Y", "CAGR", null, `HISTORY STARTS ${iso(lagDays + n - 1)}`),
    ],
  };
}

test("MF: a search lists schemes and Enter opens the highlighted fund with NAV, returns and a dash where history is short", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/mf?**", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q") ?? "";
    asked.push(q);
    return r.fulfill({ json: env(/^\d+$/.test(q) ? fund(Number(q)) : SEARCH, { source: "MFAPI.IN" }) });
  });
  await run(page, "MF test fund");
  const p = panel(page);
  await expect(p).toContainText('2 SCHEMES MATCH "TEST FUND"');
  await expect(p).toContainText("NOT AN OFFICIAL AMFI API");
  await expect(p.locator(".sr")).toContainText("900001");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("900002");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("TEST FUND 900002 - DIRECT PLAN - GROWTH");
  await expect(p).toContainText("TEST MUTUAL FUND");
  await expect(p).toContainText("INR PER UNIT");
  await expect(p).toContainText("60 DAILY NAVS");
  await expect(p.getByTestId("mf-chart")).toBeVisible();
  await expect.poll(() => asked).toEqual(["test fund", "900002"]);
  // the returns table: the cursor starts on 1D and shows its number; the 1Y row has no number and says why
  await expect(p.locator(".sr")).toContainText("1D");
  await expect(p.locator(".sr")).toContainText("+0.09%");
  for (let i = 0; i < 5; i++) await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("1Y");
  await expect(p.locator(".sr")).toContainText("HISTORY STARTS");
  expect(errors).toEqual([]);
});

test("MF: by scheme code the NAV date is shown and an old NAV is called out, not hidden", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/mf?**", (r) => r.fulfill({ json: env(fund(900003, 9), { source: "MFAPI.IN" }) }));
  await run(page, "MF 900003");
  const p = panel(page);
  await expect(p).toContainText(`ON ${iso(9)}`);
  await expect(p).toContainText("9 DAYS OLD");
  await expect(p).toContainText("NO NEWER NAV FROM THE SOURCE");
  expect(errors).toEqual([]);
});

test("MF: an unknown scheme code is a plain error with advice and no table", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/mf?**", (r) =>
    r.fulfill({ status: 404, json: { error: "NO FUND WITH SCHEME CODE 9999999: SEARCH BY NAME WITH MF <WORDS>", kind: "not_found" } }),
  );
  await run(page, "MF 9999999");
  const p = panel(page);
  await expect(p).toContainText("NO FUND WITH SCHEME CODE 9999999");
  await expect(p.locator(".sr")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("MF: the provider being down is said as PROVIDER DOWN, with nothing invented", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/mf?**", (r) => r.fulfill({ status: 503, json: { error: "all sources failed", kind: "unavailable", detail: "mfapi: unavailable (timeout)" } }));
  await run(page, "MF 900004");
  const p = panel(page);
  await expect(p).toContainText("PROVIDER DOWN");
  await expect(p.locator(".sr")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("MF: a bad argument shows usage and sends no request", async ({ page }) => {
  const { errors } = await setup(page);
  let calls = 0;
  await page.route("**/api/world/mf?**", (r) => {
    calls++;
    return r.fulfill({ json: env(SEARCH) });
  });
  await run(page, "MF ab");
  await expect(panel(page)).toContainText("USAGE: MF <FUND NAME WORDS>");
  expect(calls).toBe(0);
  expect(errors).toEqual([]);
});

test("MF: E exports the whole NAV series of the open fund", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/mf?**", (r) => r.fulfill({ json: env(fund(900005), { source: "MFAPI.IN" }) }));
  await run(page, "MF 900005");
  await expect(panel(page)).toContainText("60 DAILY NAVS");
  const csv = await exportCsv(page);
  expect(csv.name).toContain("MF_900005_NAV");
  expect(csv.text.trim().split("\n")).toHaveLength(61); // header + 60 NAVs
  expect(csv.text).toContain("date,nav");
  expect(errors).toEqual([]);
});
