import { expect, test } from "@playwright/test";
import { env, panel, run, setup } from "./p19util";

// Phase 19 step 5 end-to-end tests (mocked routes only): ECST, WECO, CENB and the market-light holidays.

const SERIES = (country: string, ind: string, source = "worldbank") => ({
  country, country_name: country === "USA" ? "United States" : country, indicator: ind, label: "Inflation, consumer prices, annual %", unit: "%", freq: "ANNUAL",
  t: [1609372800, 1640908800, 1672444800, 1703980800], v: [1.2, 4.7, 8.0, 4.1], periods: ["2020", "2021", "2022", "2023"],
  last_period: "2023", last_value: 4.1, updated: "2026-10-08", source,
});
const cell = (v: number, year: number) => ({ v, year, stale: 2026 - year > 2 });
const WECO = {
  rows: [
    { iso3: "ARG", name: "Argentina", cells: { GDPG: cell(4.4, 2025), CPI: cell(219.9, 2024), UNEMP: cell(7.1, 2025), DEBT: null, CA: cell(0.9, 2025) } },
    { iso3: "BRA", name: "Brazil", cells: { GDPG: cell(2.3, 2025), CPI: cell(5.0, 2025), UNEMP: cell(5.6, 2025), DEBT: cell(61.2, 2018), CA: cell(-2.8, 2025) } },
    { iso3: "USA", name: "United States", cells: { GDPG: cell(2.2, 2025), CPI: cell(2.7, 2025), UNEMP: cell(4.2, 2025), DEBT: cell(98.0, 2024), CA: cell(-3.9, 2025) } },
  ],
  columns: [{ alias: "GDPG", label: "GDP growth", unit: "%" }, { alias: "CPI", label: "Inflation", unit: "%" }, { alias: "UNEMP", label: "Unemployment", unit: "%" },
    { alias: "DEBT", label: "Debt", unit: "% of GDP" }, { alias: "CA", label: "Current account", unit: "% of GDP" }],
  failed: [], note: "EACH CELL IS THE COUNTRY'S MOST RECENT VALUE WITH ITS OWN DATA YEAR; YEARS ARE NOT ALIGNED ACROSS COUNTRIES", source: "worldbank",
};
const bank = (b: string, name: string, rate: number | null, next: string | null, days: number | null, note: string | null = null) => ({
  bank: b, name, last: "2026-09-17", next, after: null, days, rate, rate_as_of: rate == null ? null : "2026-10-15", rate_label: null,
  rate_note: rate == null ? "NO KEYLESS POLICY-RATE SOURCE" : null, dates: next ? ["2026-09-17", next] : [], url: `https://example.org/${b}`, note,
});
const CENB = {
  today: "2026-10-18", calendar_as_of: "2026-10-18", note: "DECISION DATES FROM EACH BANK'S PUBLISHED SCHEDULE, TRANSCRIBED 2026-10-18", notes: [],
  rows: [bank("FED", "Federal Reserve (FOMC)", 4.0, "2026-10-28", 10), bank("RBA", "Reserve Bank of Australia", null, "2026-11-03", 16),
    bank("SNB", "Swiss National Bank", null, null, null, "SNB PAGE DOES NOT LIST DECEMBER 2026 YET")],
};

test("ECST: a country indicator is charted with source, last period and update date; unknown input says what to type", async ({ page }) => {
  const { errors } = await setup(page);
  const calls: string[] = [];
  await page.route("**/api/world/stats?**", (r) => {
    const u = new URL(r.request().url());
    calls.push(`${u.searchParams.get("country")}|${u.searchParams.get("ind")}`);
    return r.fulfill({ json: env(SERIES("USA", "CPI"), { source: "worldbank" }) });
  });
  await run(page, "ECST USA CPI");
  const p = panel(page);
  await expect(p).toContainText("UNITED STATES · INFLATION, CONSUMER PRICES, ANNUAL %");
  await expect(p).toContainText("LAST 4.10 (2023)");
  await expect(p).toContainText("4 OBS FROM 2020");
  await expect(p).toContainText("SOURCE UPDATED 2026-10-08");
  expect(calls).toEqual(["USA|CPI"]);

  await run(page, "ECST usa");
  await expect(p).toContainText("GIVE AN INDICATOR AFTER THE COUNTRY");
  await run(page, "ECST");
  await expect(p).toContainText("USAGE: ECST");
  expect(errors).toEqual([]);
});

test("ECST: a DBnomics series reference and a source failure", async ({ page }) => {
  await setup(page);
  await page.route("**/api/world/stats?**", (r) => {
    const ind = new URL(r.request().url()).searchParams.get("ind")!;
    if (ind.startsWith("DBN:")) return r.fulfill({ json: env(SERIES("USA.NGDP_RPCH", "DBN", "dbnomics IMF/WEO:latest"), { source: "dbnomics IMF/WEO:latest" }) });
    return r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "worldbank: unavailable (timeout); dbnomics: unavailable (timeout)" } });
  });
  await run(page, "ECST DBN:IMF/WEO:latest/USA.NGDP_RPCH");
  await expect(panel(page)).toContainText("DBNOMICS IMF/WEO:LATEST");
  await run(page, "ECST DEU CPI");
  await expect(panel(page)).toContainText("PROVIDER DOWN");
});

test("WECO: the grid keeps each cell's year, flags old data, sorts by column and Enter opens ECST", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/weco", (r) => r.fulfill({ json: env(WECO, { source: "worldbank" }) }));
  await page.route("**/api/world/stats?**", (r) => r.fulfill({ json: env(SERIES("ARG", "CPI")) }));
  await run(page, "WECO");
  const p = panel(page);
  await expect(p).toContainText("WECO G20 · 3 COUNTRIES");
  await expect(p).toContainText("OWN DATA YEAR");
  await expect(p.locator(".sr")).toContainText("ARGENTINA");
  await expect(p.locator(".sr")).toContainText("220 (2024)");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("BRAZIL");
  await expect(p.locator(".sr")).toContainText("61.2 (2018)");
  await page.keyboard.press("2"); // sort inflation, highest first
  await expect.poll(async () => (await p.locator(".sr").textContent()) ?? "").toContain("BRAZIL");
  await page.keyboard.press("k");
  await expect(p.locator(".sr")).toContainText("ARGENTINA");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("ECST");
  await expect(p).toContainText("INFLATION, CONSUMER PRICES");
  expect(errors).toEqual([]);
});

test("CENB: policy rates, next decision with days to go, and honest gaps", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/cenb", (r) => r.fulfill({ json: env(CENB, { source: "fed / ecb / boe / boc rates + dated calendar table" }) }));
  await run(page, "CENB");
  const p = panel(page);
  await expect(p).toContainText("CENB CENTRAL BANKS · 3");
  await expect(p).toContainText("CALENDAR TABLE AS OF 2026-10-18");
  await expect(p).toContainText("OTHER BANKS HAVE NO KEYLESS RATE SOURCE");
  await expect(p.locator(".sr")).toContainText("FED");
  await expect(p.locator(".sr")).toContainText("4.00%");
  await expect(p.locator(".sr")).toContainText("2026-10-28");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("RBA");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("RBA DECISIONS: 2026-09-17 2026-11-03");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("SNB PAGE DOES NOT LIST DECEMBER 2026 YET");
  expect(errors).toEqual([]);
});

test("market lights: a holiday reads HOL and an early close reads EARLY (loaded from /api/world/holidays)", async ({ page }) => {
  await page.route("**/api/world/holidays?**", (r) => {
    const mkt = new URL(r.request().url()).searchParams.get("mkt");
    return r.fulfill({ json: env({ mkt, year: 2026, basis: mkt === "NY" ? "rules" : "public", label: "L", holidays: mkt === "NY" ? [{ date: "2026-11-26", name: "Thanksgiving Day", national: true }] : [], early: mkt === "NY" ? [{ date: "2026-11-27", name: "x" }] : [], source: "x" }) });
  });
  await page.clock.install({ time: new Date("2026-11-26T16:00:00Z") });
  await setup(page);
  const light = page.locator(".clock .mk").first();
  await expect(light).toHaveText("NY HOL");
  await expect(light).toHaveAttribute("title", /HOLIDAYS BY NYSE RULE/);
  await page.clock.setFixedTime(new Date("2026-11-27T17:30:00Z"));
  await expect(light).toHaveText("NY EARLY", { timeout: 5000 });
  await page.clock.setFixedTime(new Date("2026-12-02T16:00:00Z"));
  await expect(light).toHaveText("NY", { timeout: 5000 });
});
