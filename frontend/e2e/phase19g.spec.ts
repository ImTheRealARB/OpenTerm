import { expect, test } from "@playwright/test";
import { env, panel, run, setup } from "./p19util";

// Phase 19 step 6 end-to-end tests (mocked routes only): NRG and WETR. Numbers are made-up test data.

const nrgRow = (alias: string, id: string, label: string, group: string, unit: string, last: number | null, chg: number | null, extra = {}) => ({
  id, alias, label, group, unit, freq: "DAILY", last, date: "2026-10-16", chg, pct: chg == null || last == null ? null : (chg / (last - chg)) * 100,
  lo: last == null ? null : last * 0.8, hi: last == null ? null : last * 1.2, pos: last == null ? null : 50, n: 250, stale: false, error: null, ...extra,
});
const NRG = {
  rows: [
    nrgRow("WTI", "DCOILWTICO", "WTI CRUDE, CUSHING", "CRUDE", "$/BBL", 81.5, 1.25),
    nrgRow("BRENT", "DCOILBRENTEU", "BRENT CRUDE, EUROPE", "CRUDE", "$/BBL", 85.75, -0.5),
    nrgRow("HH", "DHHNGSP", "HENRY HUB NATURAL GAS", "GAS", "$/MMBTU", 2.95, 0.05, { stale: true, date: "2026-10-02" }),
    nrgRow("HEAT", "DHOILNYH", "NY HARBOR NO.2 HEATING OIL", "PRODUCTS", "$/GAL", null, null, { error: "FRED DOWN", date: null }),
  ],
  spread: { value: 4.25, date: "2026-10-16", label: "BRENT - WTI", unit: "$/BBL" },
  failed: ["HEAT"], groups: ["CRUDE", "GAS", "PRODUCTS", "RETAIL"],
  note: "PRICES ONLY: EIA WEEKLY STOCKS AND PRODUCTION ARE NOT ON THE KEYLESS FRED FEED. SPOT PRICES LAG ONE TO THREE BUSINESS DAYS.",
};
const day = (date: string, tmax: number, tmin: number, hdd: number, cdd: number, sky = "CLEAR") => ({ date, tmax, tmin, tmean: (tmax + tmin) / 2, precip: 0, wind: 12, code: 0, sky, hdd, cdd });
const basketRow = (city: string, hdd: number, cdd: number, days = 7) => ({ city, hdd, cdd, days, tmean: 12.3, tmax: 20, tmin: 4 });
const WETR_BASKET = {
  basket: { rows: [basketRow("New York", 80.5, 2), basketRow("Houston", 10, 45.5), basketRow("London", 70, 0, 6)], average: { hdd: 53.5, cdd: 15.8 }, weighting: "EQUAL-WEIGHTED, NOT WEIGHTED BY GAS OR POWER DEMAND" },
  place: null, forecast: null, alerts: null, base_f: 65, note: "DEGREE DAYS: F-DAYS, BASE 65 F, DAILY MEAN = (MAX + MIN) / 2. TEMPERATURES IN C.",
};
const WETR_PLACE = (alerts: unknown) => ({
  ...WETR_BASKET,
  place: { name: "Houston, Texas, US", lat: 29.76, lon: -95.36, cc: "US", tz: "America/Chicago", others: ["Houston, CA"] },
  forecast: { lat: 29.76, lon: -95.36, tz: "America/Chicago", days: [day("2026-10-18", 30, 20, 0, 5.5, "PARTLY CLOUDY"), day("2026-10-19", 28, 18, 0, 3.1, "RAIN")], hdd: 0, cdd: 8.6, days_counted: 2 },
  alerts,
});

test("NRG: board with spread, stale and failed rows; Enter opens the series on FRED; NRG <alias> goes straight to FRED", async ({ page }) => {
  const { errors } = await setup(page);
  const fred: string[] = [];
  await page.route("**/api/world/nrg", (r) => r.fulfill({ json: env(NRG, { source: "FRED CSV (SERIES REPUBLISHED FROM EIA / US ENERGY INFORMATION ADMINISTRATION)" }) }));
  await page.route("**/api/fred?**", (r) => {
    fred.push(new URL(r.request().url()).searchParams.get("id") ?? "");
    return r.fulfill({ status: 404, json: { error: "NO FRED SERIES (TEST)", kind: "not_found" } });
  });
  await run(page, "NRG");
  const p = panel(page);
  await expect(p).toContainText("NRG ENERGY · 4 SERIES");
  await expect(p).toContainText("BRENT - WTI 4.25 $/BBL (2026-10-16)");
  await expect(p).toContainText("PRICES ONLY");
  await expect(p).toContainText("HEAT DID NOT ANSWER");
  await expect(p.locator(".sr")).toContainText("WTI");
  await expect(p.locator(".sr")).toContainText("81.50");
  await expect(p.locator(".sr")).toContainText("+1.25");
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("HH");
  await expect(p.locator(".sr")).toContainText("2.950");
  await expect(p.locator(".sr")).toContainText("STALE");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("ERR");
  await page.keyboard.press("k");
  await page.keyboard.press("k");
  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("FRED");
  await expect.poll(() => fred).toContain("DCOILBRENTEU");

  await run(page, "NRG wti");
  await expect(p.locator(".ph")).toContainText("FRED");
  await expect.poll(() => fred).toContain("DCOILWTICO");
  await run(page, "NRG wcestus1");
  await expect(p).toContainText("UNKNOWN ENERGY SERIES WCESTUS1");
  expect(errors).toEqual([]);
});

test("WETR: basket by default, place forecast with alerts, B toggles, honest notes when alerts are skipped or the place is unknown", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  const alert = { event: "Flood Warning", severity: "Severe", urgency: "Expected", area: "Harris, TX", headline: null, onset: null, ends: "2026-10-18T20:15:00-05:00" };
  await page.route("**/api/world/wetr?**", (r) => {
    const place = new URL(r.request().url()).searchParams.get("place") ?? "";
    asked.push(place);
    if (place === "Houston") return r.fulfill({ json: env(WETR_PLACE({ status: "OK", items: [alert], note: null }), { source: "open-meteo (forecast) + nws (alerts)" }) });
    if (place === "Austin") return r.fulfill({ json: env(WETR_PLACE({ status: "SKIPPED", items: [], note: "NWS ALERTS SKIPPED: SET SEC_USER_AGENT IN .ENV (NAME AND CONTACT), WEATHER.GOV REQUIRES A USER-AGENT THAT NAMES A CONTACT" })) });
    if (place === "Zzqq") return r.fulfill({ status: 404, json: { error: "NO PLACE FOUND FOR ZZQQ", kind: "not_found" } });
    return r.fulfill({ json: env(WETR_BASKET, { source: "open-meteo (forecast) + nws (alerts)" }) });
  });
  await run(page, "WETR");
  const p = panel(page);
  await expect(p).toContainText("WETR DEMAND-CITY BASKET");
  await expect(p).toContainText("EQUAL-WEIGHTED, NOT WEIGHTED BY GAS OR POWER DEMAND");
  await expect(p).toContainText("BASKET AVERAGE HDD 53.5");
  await expect(p).toContainText("FORECAST MODEL OUTPUT, NOT AN OBSERVATION");
  await expect(p.locator(".sr")).toContainText("NEW YORK");
  await expect(p.locator(".sr")).toContainText("80.5");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("HOUSTON");

  await run(page, "WETR Houston");
  await expect(p).toContainText("HOUSTON, TEXAS, US · 7-DAY FORECAST");
  await expect(p).toContainText("0.0 HDD · 8.6 CDD OVER 2 DAYS");
  await expect(p).toContainText("NWS ALERTS: 1 ACTIVE");
  await expect(p).toContainText("SEVERE · FLOOD WARNING · HARRIS, TX UNTIL 2026-10-18 20:15");
  await expect(p).toContainText("OTHER MATCHES: HOUSTON, CA");
  await expect(p.locator(".sr")).toContainText("2026-10-18");
  await expect(p.locator(".sr")).toContainText("PARTLY CLOUDY");
  await page.keyboard.press("b");
  await expect(p).toContainText("DEMAND-CITY BASKET");
  await page.keyboard.press("b");
  await expect(p).toContainText("7-DAY FORECAST");

  await run(page, "WETR Austin");
  await expect(p).toContainText("NWS ALERTS SKIPPED: SET SEC_USER_AGENT");
  await run(page, "WETR Zzqq");
  await expect(p).toContainText("NO PLACE FOUND FOR ZZQQ");
  expect(asked).toEqual(expect.arrayContaining(["", "Houston", "Austin", "Zzqq"]));
  expect(errors).toEqual([]);
});
