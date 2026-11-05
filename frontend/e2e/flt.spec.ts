import { expect, test } from "@playwright/test";
import { env, exportCsv, panel, run, setup } from "./p19util";

// FLT end-to-end tests (mocked routes only, no network, no OpenSky account). The aircraft are made-up test data in the shape the backend returns.
// NOTE: written but NOT run in the session that created it (Playwright was off limits there): run it before relying on it.

const seen = Math.floor(Date.now() / 1000) - 3;
const plane = (icao24: string, callsign: string, over = {}) => ({
  icao24, callsign, country: "United Kingdom", lat: 51.5, lon: -0.1, alt_m: 3048, geo_alt_m: 3100, alt_ft: 10000, speed_ms: 128.5, speed_kt: 250,
  heading: 271, vrate_ms: -8.13, vrate_fpm: -1600, on_ground: false, squawk: "4521", spi: false, source: "ADS-B", seen, age_s: 3, ...over,
});
const FLT = (rows: unknown[], over = {}) => ({
  area: "LONDON", kind: "AREA", box: [51.3, -0.6, 51.7, 0.2], rows, truncated: 0, received: rows.length, no_position: 0, source_time: seen + 3,
  credits_cost: 1, credits_remaining: 397, authenticated: false, fixture: false,
  access: "ANONYMOUS: LIMITED CREDITS (400 A DAY, POSITIONS EVERY 10 S). SET OPENSKY_CLIENT_ID AND OPENSKY_CLIENT_SECRET IN APIKEYS FOR MORE",
  note: "AS REPORTED BY AIRCRAFT TRANSPONDERS (ADS-B). COVERAGE IS PARTIAL: AIRCRAFT OUT OF RANGE DO NOT APPEAR OR ARE FILTERED.",
  country_note: "COUNTRY IS WHERE THE AIRCRAFT IS REGISTERED, NOT WHERE IT IS FLYING OR GOING", ...over,
});

test("FLT: aircraft listed, detail follows the cursor, honest labels and credits are on screen", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/flt?**", (r) => {
    asked.push(new URL(r.request().url()).searchParams.get("q") ?? "");
    return r.fulfill({ json: env(FLT([plane("400a1b", "TST123"), plane("406c11", "TST456", { on_ground: true, alt_m: null, alt_ft: null, vrate_fpm: null })]), { source: "OPENSKY" }) });
  });
  await run(page, "FLT LONDON");
  const p = panel(page);
  await expect(p).toContainText("2 SHOWN OF 2 HEARD");
  await expect(p).toContainText("AS REPORTED BY AIRCRAFT TRANSPONDERS");
  await expect(p).toContainText("COVERAGE IS PARTIAL");
  await expect(p.getByTestId("flt-access")).toContainText("ANONYMOUS: LIMITED CREDITS");
  await expect(p.getByTestId("flt-access")).toContainText("397 CREDITS LEFT");
  await expect(p.locator(".sr")).toContainText("TST123");
  await expect(p.getByTestId("flt-detail")).toContainText("ICAO24 400a1b");
  await expect(p.getByTestId("flt-detail")).toContainText("10,000 FT (3,048 M)");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("TST456");
  await expect(p.getByTestId("flt-detail")).toContainText("ON THE GROUND");
  expect(asked[0]).toBe("LONDON");
  expect(errors).toEqual([]);
});

test("FLT: an empty box says it proves nothing about the sky", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/flt?**", (r) => r.fulfill({ json: env(FLT([]), { source: "OPENSKY" }) }));
  await run(page, "FLT BOX 0 0 1 1");
  await expect(panel(page).getByTestId("flt-quiet")).toContainText("DOES NOT MEAN THE SKY IS EMPTY");
  expect(errors).toEqual([]);
});

test("FLT: spent credits are shown with the wait, as PROVIDER DOWN, with no rows", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/flt?**", (r) =>
    r.fulfill({ status: 503, json: { error: "OPENSKY ANONYMOUS CREDITS EXHAUSTED OR RATE LIMITED: RETRY IN 60 MIN", kind: "unavailable" } }),
  );
  await run(page, "FLT NYC");
  const p = panel(page);
  await expect(p).toContainText("PROVIDER DOWN");
  await expect(p).toContainText("RETRY IN 60 MIN");
  // The grid is always mounted, so its screen-reader mirror (.sr) always exists; "no rows" means it names no aircraft.
  await expect(p.locator(".sr")).toHaveText("");
  expect(errors).toEqual([]);
});

test("FLT: a bad box shows the usage line", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/flt?**", (r) => r.fulfill({ status: 400, json: { error: "BOX TOO BIG: AT MOST 100 SQUARE DEGREES", kind: "bad_request" } }));
  await run(page, "FLT BOX 0 0 50 50");
  await expect(panel(page)).toContainText("BOX TOO BIG");
  await expect(panel(page)).toContainText("USAGE: FLT <LONDON");
  expect(errors).toEqual([]);
});

test("FLT: N steps to the next city and E exports both unit systems", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/flt?**", (r) => {
    asked.push(new URL(r.request().url()).searchParams.get("q") ?? "");
    return r.fulfill({ json: env(FLT([plane("400a1b", "TST123")]), { source: "OPENSKY" }) });
  });
  await run(page, "FLT LONDON");
  await expect(panel(page).locator(".sr")).toContainText("TST123");
  await page.keyboard.press("n");
  await expect.poll(() => asked).toContain("NYC");
  await expect(panel(page).locator(".sr")).toContainText("TST123");
  const csv = await exportCsv(page);
  expect(csv.name).toContain("FLT_");
  expect(csv.text).toContain("BARO_ALT_M");
  expect(csv.text).toContain("ALT_FT");
  expect(csv.text).toContain("400a1b");
  expect(errors).toEqual([]);
});
