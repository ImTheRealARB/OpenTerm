import { expect, test } from "@playwright/test";
import { bars, env, now, panel, run, setup } from "./p19util";

// Phase 19 step 9 end-to-end tests (mocked routes only): SECF fund rows from AMFI NAV, and a GP chart served by the NSE archive fallback.
// Numbers are made-up test data.

const fund = (code: string, plan: string, option: string, nav: number) => ({
  code, isin: `INF000K0${code}`, isin_reinv: null, name: "Axis Children's Fund", plan, option, nav, date: "2026-10-16",
  category: "Open Ended Schemes(Children's Fund)", amc: "Axis Mutual Fund",
});
const NAV = {
  query: "axis children", total: 2, shown: 2, nav_date: "2026-10-16", schemes: 186,
  items: [fund("135762", "Direct Plan", "Growth Option", 29.396), fund("135759", "Regular Plan", "Growth Option", 25.5801)],
  note: "AMFI NAV: END-OF-DAY NET ASSET VALUE PER UNIT, PUBLISHED BY AMFI IN THE EVENING. NOT A MARKET PRICE.",
};
const UNIVERSE = {
  columns: ["symbol", "name", "last", "chg", "pct", "volume", "mcap", "country", "ipo", "sector", "industry"],
  rows: [["AXP", "American Express Company Common Stock", 300, 1, 0.3, 1e6, 2e11, 1, null, 1, 1]],
  sectors: ["", "Financials"], industries: ["", "x"], countries: ["", "United States"], count: 1, as_of_text: "Data as of Oct 16, 2026", market: "us",
  source: "nasdaq_screener", as_of: now(),
};

test("SECF: a name search also lists AMFI fund schemes; M shows them with NAV and date, Enter explains there is no chart", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/screener", (r) => r.fulfill({ json: env(UNIVERSE, { source: "nasdaq_screener" }) }));
  await page.route("**/api/search?**", (r) => r.fulfill({ json: env([]) }));
  await page.route("**/api/world/mfnav?**", (r) => {
    asked.push(new URL(r.request().url()).searchParams.get("q") ?? "");
    return r.fulfill({ json: env(NAV, { source: "amfi" }) });
  });
  await run(page, "SECF axis children");
  const p = panel(page);
  await expect(p.getByTestId("secf-funds")).toContainText("2 AMFI FUND SCHEMES MATCH · NAV DATE 2026-10-16 · AMFI · M SHOWS FUNDS");
  expect(asked).toContain("axis children");
  await expect(async () => {
    await page.keyboard.press("m");
    await expect(p.getByTestId("secf-funds")).toContainText("M BACK TO SECURITIES", { timeout: 500 });
  }).toPass();
  await expect(p).toContainText("NOT A MARKET PRICE");
  await expect(p.locator(".sr")).toContainText("135762");
  await expect(p.locator(".sr")).toContainText("29.3960");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("Regular Plan");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("NO CHART: AMFI GIVES THE LATEST NAV ONLY");
  await page.keyboard.press("m");
  await expect(p.getByTestId("secf-funds")).toContainText("M SHOWS FUNDS");
  expect(errors).toEqual([]);
});

test("SECF: an AMFI failure is named and does not hide the security matches", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/screener", (r) => r.fulfill({ json: env(UNIVERSE, { source: "nasdaq_screener" }) }));
  await page.route("**/api/search?**", (r) => r.fulfill({ json: env([]) }));
  await page.route("**/api/world/mfnav?**", (r) => r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "amfi: unavailable (timeout)" } }));
  await run(page, "SECF american");
  const p = panel(page);
  await expect(p).toContainText("AMFI NAV: PROVIDER DOWN");
  await expect(p.locator(".sr")).toContainText("AXP");
  expect(errors).toEqual([]);
});

test("GP: daily bars from the NSE archive fallback carry the archive label and the file count", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/history?**", (r) => {
    const u = new URL(r.request().url());
    const b = bars(u.searchParams.get("symbol")!, u.searchParams.get("range") ?? "", "1d");
    return r.fulfill({ json: env({ ...b, currency: "INR", source: "NSE ARCHIVE, EOD, built from 10 daily files (INCOMPLETE)" }, {
      source: "NSE ARCHIVE, EOD, built from 10 daily files (INCOMPLETE)", fallback_from: ["yahoo"],
    }) });
  });
  await run(page, "RELIANCE.NS GP");
  const p = panel(page);
  await expect(p).toContainText("NSE ARCHIVE, EOD, BUILT FROM 10 DAILY FILES (INCOMPLETE)");
  expect(errors).toEqual([]);
});
