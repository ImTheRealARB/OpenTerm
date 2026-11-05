import { expect, test, type Page } from "@playwright/test";
import { env, gauge, panel, run, setup } from "./p19util";

// MAP end-to-end tests (mocked routes only, no network, no AISstream key). Every row below is made-up test data in the shape the server answers.
// The canvas is invisible to the DOM, so the tests read the layer list, the detail list, the `.sr` live region and the map.* gauges.

const t = Math.floor(Date.now() / 1000);
const QUAKES = {
  rows: [
    { id: "q1", lat: 10, lon: 20, depth_km: 12, mag: 6.4, mag_type: "mww", place: "TEST QUAKE NEAR THE CENTRE", time: t - 600, url: null, tsunami: false, alert: null, status: "reviewed" },
    { id: "q2", lat: -30, lon: 140, depth_km: 33, mag: 4.9, mag_type: "mb", place: "TEST QUAKE FAR AWAY", time: t - 7200, url: null, tsunami: true, alert: null, status: "automatic" },
  ],
  skipped: 0, title: "TEST FEED", generated: t, note: "TEST QUAKES NOTE",
};
const EVENTS = {
  rows: [{ id: "E1", title: "TEST CYCLONE", category: "severeStorms", category_title: "Severe Storms", lat: 14, lon: 80, time: t - 3600, mag: 60, mag_unit: "kts", source: "JTWC", url: null, track: [[86, 11], [80, 14]] }],
  skipped: 0, title: "", note: "TEST EVENTS NOTE",
};
const PORTS = {
  rows: [
    { id: "p1", name: "TEST PORT ONE", country: "TESTLAND", locode: "TL ONE", lat: 1.26, lon: 103.8, rank: 1, calls_per_day: 115, newest: "2026-10-30" },
    { id: "p2", name: "TEST PORT TWO", country: "TESTLAND", locode: "TL TWO", lat: 51.9, lon: 4.2, rank: 2, calls_per_day: 70, newest: "2026-10-30" },
  ],
  skipped: 0, newest: "2026-10-30", note: "TEST PORTS NOTE",
};
const CHOKE = {
  rows: [
    { id: "SUEZ", name: "SUEZ", box: [29.8, 32.2, 31.4, 32.7], lat: 30.6, lon: 32.45 },
    { id: "HORMUZ", name: "HORMUZ", box: [25.8, 55.6, 27.0, 57.0], lat: 26.4, lon: 56.3 },
  ],
  note: "TEST CHOKEPOINT NOTE",
};
const ship = (mmsi: number, name: string, over = {}) => ({
  mmsi, name, imo: null, type: "CARGO", type_code: 70, sog: 8.5, cog: 355, heading: 356, nav: 0, nav_name: "UNDERWAY (ENGINE)",
  dest: null, eta: null, length: null, draught: null, lat: 26.4, lon: 56.3, seen: t - 30, static_age_s: null, remembered: false, age_s: 30, ...over,
});

/** Mocks every layer route. `over` replaces single routes (a function answering the request). */
async function mockLayers(page: Page, over: Record<string, (r: import("@playwright/test").Route) => Promise<void>> = {}) {
  const routes: Record<string, (r: import("@playwright/test").Route) => Promise<void>> = {
    "**/api/world/geo/quakes": (r) => r.fulfill({ json: env(QUAKES, { source: "USGS TEST" }) }),
    "**/api/world/geo/events": (r) => r.fulfill({ json: env(EVENTS, { source: "NASA EONET TEST" }) }),
    "**/api/world/geo/ports": (r) => r.fulfill({ json: env(PORTS, { source: "IMF PORTWATCH TEST" }) }),
    "**/api/world/geo/chokepoints": (r) => r.fulfill({ json: env(CHOKE, { source: "OPENTERM PRESETS TEST" }) }),
    "**/api/world/ais?**": (r) =>
      r.fulfill({ status: 424, json: { error: "KEY REQUIRED", key: "AISSTREAM_API_KEY", detail: "KEY REQUIRED: set AISSTREAM_API_KEY in APIKEYS" } }),
    ...over,
  };
  for (const [url, handler] of Object.entries(routes)) await page.route(url, handler);
}

const row = (page: Page, id: string) => panel(page).getByTestId(`map-layer-${id}`);

test("MAP opens with the keyless layers on, vessels off, and every layer says what it holds and how old it is", async ({ page }) => {
  const { errors } = await setup(page);
  await mockLayers(page);
  await run(page, "MAP");
  await expect(row(page, "ports")).toContainText("2 ·");
  await expect(row(page, "chokepoints")).toContainText("2 ·");
  await expect(row(page, "quakes")).toContainText("2 ·");
  await expect(row(page, "events")).toContainText("2 ·"); // the cyclone: a dot and a path
  await expect(row(page, "vessels")).toContainText("OFF");
  await expect(row(page, "vessels")).toHaveAttribute("data-on", "0");
  // the layer card says source, shapes, colour meaning, refresh rule and the key the layer needs
  await page.keyboard.press("1");
  const card = panel(page).getByTestId("map-layer-card");
  await expect(card).toContainText("SOURCE AISSTREAM");
  await expect(card).toContainText("REFRESH");
  await expect(card).toContainText("NEEDS KEY AISSTREAM_API_KEY");
  await expect.poll(() => gauge(page, "map.shapes")).toBe(2 + 2 + 2 + 2);
  expect(await gauge(page, "map.drawMs")).toBeLessThan(50);
  expect(errors).toEqual([]);
});

test("MAP: without a key only the vessels layer says KEY REQUIRED; the other layers keep drawing", async ({ page }) => {
  const { errors } = await setup(page);
  await mockLayers(page);
  await run(page, "MAP");
  await expect(row(page, "quakes")).toContainText("2 ·");
  await page.keyboard.press("v"); // listen for ships in the box nearest the centre
  await expect(row(page, "vessels")).toContainText("KEY REQUIRED: set AISSTREAM_API_KEY in APIKEYS");
  await expect(row(page, "quakes")).toContainText("2 ·");
  await expect(row(page, "ports")).not.toContainText("KEY REQUIRED");
  expect(errors).toEqual([]);
});

test("MAP: a failing layer shows ERR, the others are unaffected, and F5 retries", async ({ page }) => {
  const { errors } = await setup(page);
  let calls = 0;
  await mockLayers(page, {
    "**/api/world/geo/quakes": (r) => {
      calls++;
      return calls === 1 ? r.fulfill({ status: 503, json: { error: "unavailable", message: "USGS DOWN" } }) : r.fulfill({ json: env(QUAKES, { source: "USGS TEST" }) });
    },
  });
  await run(page, "MAP");
  await expect(row(page, "quakes")).toContainText("ERR");
  await expect(row(page, "ports")).toContainText("2 ·");
  await page.keyboard.press("F5");
  await expect(row(page, "quakes")).toContainText("2 ·");
  expect(errors).toEqual([]);
});

test("MAP: keys switch layers, Enter / N / P pick dots, the detail list shows name, source and age, Esc drops the pick", async ({ page }) => {
  const { errors } = await setup(page);
  await mockLayers(page);
  await run(page, "MAP QUAKES");
  const p = panel(page);
  await expect(row(page, "quakes")).toContainText("2 ·");
  await expect(row(page, "ports")).toContainText("OFF"); // only the named layer is on
  await page.keyboard.press("Enter"); // nearest to the centre cross
  const detail = p.getByTestId("map-detail");
  await expect(detail).toBeVisible();
  await expect(p.getByTestId("map-sr")).toContainText("SELECTED QUAKES");
  await expect(detail).toContainText("SOURCE");
  await expect(detail).toContainText("USGS TEST");
  await expect(detail).toContainText("AGO"); // observed and fetched ages
  const first = await p.getByTestId("map-sr").textContent();
  await page.keyboard.press("n");
  await expect.poll(async () => p.getByTestId("map-sr").textContent()).not.toBe(first);
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
  // number key toggles a layer on and off
  await page.keyboard.press("2");
  await expect(row(page, "ports")).toHaveAttribute("data-on", "1");
  await page.keyboard.press("2");
  await expect(row(page, "ports")).toHaveAttribute("data-on", "0");
  // J moves the layer cursor (a number key leaves it on that layer, here PORTS) and Space toggles the layer under it (CHOKEPOINTS)
  await expect(row(page, "chokepoints")).toHaveAttribute("data-on", "0");
  await page.keyboard.press("j");
  await page.keyboard.press(" ");
  await expect(row(page, "chokepoints")).toHaveAttribute("data-on", "1");
  expect(errors).toEqual([]);
});

test("MAP VESSELS HORMUZ: centres on the box, loads its ships, labels test data and drops ships outside the box", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await mockLayers(page, {
    "**/api/world/ais?**": (r) => {
      asked.push(new URL(r.request().url()).searchParams.get("q") ?? "");
      return r.fulfill({
        json: env(
          {
            area: "HORMUZ", box: [25.8, 55.6, 27, 57], truncated: 0, received: 9, capped: false, listened_s: 8, fixture: true, note: "TEST AIS NOTE",
            rows: [ship(900000001, "DOC SHAPE ONE"), ship(900000002, "DOC SHAPE AWAY", { lat: 30.2, lon: 32.5 })],
          },
          { source: "aisstream (DOC-SHAPED fixture, NOT A RECORDING)" },
        ),
      });
    },
  });
  await run(page, "MAP VESSELS HORMUZ");
  await expect(row(page, "vessels")).toContainText("1 ·");
  await expect(row(page, "vessels")).toContainText("FIXTURE");
  expect(asked).toEqual(["HORMUZ"]);
  await expect(panel(page)).toContainText("DOC-SHAPED TEST DATA");
  await expect(panel(page)).toContainText("1 POSITIONS OUTSIDE THE BOX LEFT OFF THE MAP");
  // an area on the command line shows its box, and the view is on it
  await expect(row(page, "chokepoints")).toHaveAttribute("data-on", "1");
  await expect.poll(() => gauge(page, "map.centerLat")).toBeGreaterThan(26.3);
  expect(await gauge(page, "map.centerLat")).toBeLessThan(26.5);
  expect(await gauge(page, "map.centerLon")).toBeGreaterThan(56.2);
  expect(await gauge(page, "map.zoom")).toBeGreaterThan(6);
  expect(errors).toEqual([]);
});

test("MAP: an unknown word is a usage error, never ignored", async ({ page }) => {
  const { errors } = await setup(page);
  await mockLayers(page);
  await run(page, "MAP NARNIA");
  await expect(panel(page)).toContainText("USAGE: MAP");
  await expect(panel(page)).toContainText("UNKNOWN WORD NARNIA");
  expect(errors).toEqual([]);
});

test("MAP: + / - / 0 zoom about the centre and the mouse wheel zooms too", async ({ page }) => {
  const { errors } = await setup(page);
  await mockLayers(page);
  await run(page, "MAP");
  await expect(row(page, "quakes")).toContainText("2 ·");
  const z0 = await gauge(page, "map.zoom");
  await page.keyboard.press("+");
  await expect.poll(() => gauge(page, "map.zoom")).toBeCloseTo(z0 + 1, 3);
  await page.keyboard.press("-");
  await expect.poll(() => gauge(page, "map.zoom")).toBeCloseTo(z0, 3);
  await page.keyboard.press("+");
  await page.keyboard.press("+");
  await page.keyboard.press("0");
  await expect.poll(() => gauge(page, "map.zoom")).toBeCloseTo(z0, 3);
  const box = (await page.getByTestId("map-canvas").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -400);
  await expect.poll(() => gauge(page, "map.zoom")).toBeGreaterThan(z0 + 0.5);
  expect(errors).toEqual([]);
});

test("MAP: a click on a dot picks it, and arrows pan", async ({ page }) => {
  const { errors } = await setup(page);
  await mockLayers(page);
  await run(page, "MAP QUAKES");
  await expect(row(page, "quakes")).toContainText("2 ·");
  await page.keyboard.press("Enter"); // pick the nearest dot...
  await page.keyboard.press("Enter"); // ...and a second Enter centres on it, zoomed in
  await expect.poll(() => gauge(page, "map.zoom")).toBeGreaterThanOrEqual(6);
  const lon0 = await gauge(page, "map.centerLon");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => gauge(page, "map.centerLon")).toBeGreaterThan(lon0);
  await page.keyboard.press("Escape");
  // the picked dot is at the centre of the canvas after centring: click the middle of the canvas
  await page.keyboard.press("ArrowLeft");
  const box = (await page.getByTestId("map-canvas").boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(panel(page).getByTestId("map-sr")).toContainText("SELECTED QUAKES");
  expect(errors).toEqual([]);
});

test("AIS: M opens the same area on the map", async ({ page }) => {
  const { errors } = await setup(page);
  await mockLayers(page, {
    "**/api/world/ais?**": (r) =>
      r.fulfill({
        json: env({ area: "HORMUZ", box: [25.8, 55.6, 27, 57], truncated: 0, received: 9, capped: false, listened_s: 8, fixture: false, note: "TEST AIS NOTE", rows: [ship(900000001, "TEST ONE")] }, { source: "aisstream" }),
      }),
  });
  await run(page, "AIS HORMUZ");
  await expect(panel(page)).toContainText("1 SHIPS IN 8 S");
  await page.keyboard.press("m");
  await expect(row(page, "vessels")).toContainText("1 ·");
  await expect.poll(() => gauge(page, "map.centerLat")).toBeGreaterThan(26.3);
  expect(errors).toEqual([]);
});

const FLT_PAYLOAD = {
  area: "FRANKFURT", kind: "AREA", box: [49.8, 8.2, 50.3, 9.0],
  rows: [
    { icao24: "3c6444", callsign: "DLH400", country: "Germany", lat: 50.0, lon: 8.5, alt_m: 3048, geo_alt_m: 3100, alt_ft: 10000, speed_ms: 120, speed_kt: 233, heading: 270, vrate_ms: 0, vrate_fpm: 0, on_ground: false, squawk: "1000", spi: false, source: "ADS-B", seen: t - 5, age_s: 5 },
    { icao24: "3c6445", callsign: "TEST2", country: "Germany", lat: 50.05, lon: 8.6, alt_m: 0, geo_alt_m: null, alt_ft: 0, speed_ms: 0, speed_kt: 0, heading: null, vrate_ms: null, vrate_fpm: null, on_ground: true, squawk: "", spi: false, source: "ADS-B", seen: t - 20, age_s: 20 },
  ],
  truncated: 0, received: 2, no_position: 0, source_time: t, credits_cost: 1, credits_remaining: 397, authenticated: false, access: "TEST ACCESS", note: "TEST FLIGHTS NOTE", country_note: "", fixture: false,
};

test("MAP: key 6 loads aircraft for the FLT city nearest the centre cross, shows heading in the detail list, and A loads again", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await mockLayers(page, {
    "**/api/world/flt?**": (r) => {
      asked.push(new URL(r.request().url()).searchParams.get("q") ?? "");
      return r.fulfill({ json: env(FLT_PAYLOAD, { source: "OPENSKY TEST" }) });
    },
  });
  await run(page, "MAP");
  await expect(row(page, "flights")).toContainText("OFF");
  // Wait for the chokepoint list first: when it arrives MAP re-applies the typed command and switches layers it did not name OFF again.
  await expect(row(page, "chokepoints")).toContainText("2 ·");
  await page.keyboard.press("6");
  await expect(row(page, "flights")).toContainText("2 ·");
  expect(asked).toEqual(["FRANKFURT"]); // the world view's centre is nearest to Frankfurt of the seven FLT cities
  await page.keyboard.press("a");
  await expect.poll(() => asked.length).toBe(2); // A loads (fresh) again
  expect(errors).toEqual([]);
});
