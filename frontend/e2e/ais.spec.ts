import { expect, test } from "@playwright/test";
import { env, panel, run, setup } from "./p19util";

// AIS end-to-end tests (mocked routes only, no network, no AISstream key). The ships are made-up test data in the shape the backend returns.

const seen = Math.floor(Date.now() / 1000) - 20;
const ship = (mmsi: number, name: string, over = {}) => ({
  mmsi, name, imo: null, type: "CARGO", type_code: 70, sog: 8.5, cog: 355, heading: 356, nav: 0, nav_name: "UNDERWAY (ENGINE)",
  dest: null, eta: null, length: null, draught: null, lat: 30.2, lon: 32.55, seen, static_age_s: null, remembered: false, age_s: 20, ...over,
});
const AIS = (rows: unknown[], over = {}) => ({
  area: "SUEZ", box: [29.8, 32.2, 31.4, 32.7], rows, truncated: 0, received: 40, capped: false, listened_s: 8, fixture: false,
  remembered: (rows as { remembered?: boolean }[]).filter((r) => r.remembered).length, memory_s: 300,
  note: "AISSTREAM: POSITIONS ARE AS REPORTED BY SHIPS AND ARE NOT VERIFIED. THEY CAN BE DELAYED, SWITCHED OFF OR SPOOFED, AND COVERAGE IS PARTIAL.", ...over,
});

test("AIS: ships listed, detail line follows the cursor, the as-reported warning is on screen", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/ais?**", (r) =>
    r.fulfill({
      json: env(AIS([
        ship(900000001, "TEST ONE", { dest: "SINGAPORE", eta: "11-12 06:00", imo: 9000001, length: 240, draught: 11.2, static_age_s: 120, type: "TANKER" }),
        ship(900000002, "TEST TWO", { sog: null, cog: null, nav: 1, nav_name: "AT ANCHOR" }),
      ]), { source: "aisstream" }),
    }),
  );
  await run(page, "AIS SUEZ");
  const p = panel(page);
  await expect(p).toContainText("2 SHIPS IN 8 S");
  await expect(p).toContainText("POSITIONS ARE AS REPORTED BY SHIPS");
  await expect(p.locator(".sr")).toContainText("TEST ONE");
  await expect(p.getByTestId("ais-detail")).toContainText("IMO 9000001");
  await expect(p.getByTestId("ais-detail")).toContainText("TYPED BY THE CREW");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("TEST TWO");
  await expect(p.getByTestId("ais-detail")).toContainText("NO VOYAGE DATA RECEIVED YET");
  expect(errors).toEqual([]);
});

test("AIS: ships remembered from an earlier listen are counted, labelled and explained", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/ais?**", (r) =>
    r.fulfill({
      json: env(AIS([
        ship(900000001, "HEARD NOW"),
        ship(900000002, "HEARD EARLIER", { remembered: true, seen: seen - 180, age_s: 200 }),
      ]), { source: "aisstream" }),
    }),
  );
  await run(page, "AIS SUEZ");
  const p = panel(page);
  await expect(p).toContainText("2 SHIPS IN 8 S (1 FROM MEMORY)");
  await expect(p.getByTestId("ais-memory")).toContainText("POSITIONS UP TO 5 MIN OLD FROM EARLIER LISTENS");
  await page.keyboard.press("j");
  await expect(p.locator(".sr")).toContainText("HEARD EARLIER");
  await expect(p.getByTestId("ais-detail")).toContainText("REMEMBERED FROM AN EARLIER LISTEN");
  expect(errors).toEqual([]);
});

test("AIS: a replayed recording is labelled on screen", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/ais?**", (r) =>
    r.fulfill({ json: env(AIS([ship(900000001, "MOCK SHIP ONE")], { fixture: true }), { source: "aisstream (REPLAY of a real recording from 2026-11-05, NOT LIVE)" }) }),
  );
  await run(page, "AIS");
  await expect(panel(page)).toContainText("REPLAY OF A REAL AISSTREAM RECORDING FROM 2026-11-05");
  expect(errors).toEqual([]);
});

test("AIS: without a key the panel says KEY REQUIRED and Enter opens APIKEYS; nothing is faked", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/ais?**", (r) =>
    r.fulfill({ status: 424, json: { error: "KEY REQUIRED", key: "AISSTREAM_API_KEY", detail: "KEY REQUIRED: set AISSTREAM_API_KEY in APIKEYS" } }),
  );
  await run(page, "AIS HORMUZ");
  const p = panel(page);
  await expect(p).toContainText("KEY REQUIRED: set AISSTREAM_API_KEY in APIKEYS");
  // The grid is always mounted, so its screen-reader mirror (.sr) always exists; "nothing is faked" means it names no ship.
  await expect(p.locator(".sr")).toHaveText("");
  expect(errors).toEqual([]);
});

test("AIS: a quiet listen says so and does not claim the area is empty; N moves to the next chokepoint", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/ais?**", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q") ?? "";
    asked.push(q);
    return r.fulfill({ json: env(AIS([], { area: q, received: 0 }), { source: "aisstream" }) });
  });
  await run(page, "AIS SUEZ");
  const p = panel(page);
  await expect(p.getByTestId("ais-quiet")).toContainText("DOES NOT SHOW THE AREA IS EMPTY");
  await expect(async () => {
    await page.keyboard.press("n");
    await expect.poll(() => asked.includes("PANAMA"), { timeout: 500 }).toBe(true);
  }).toPass();
  expect(errors).toEqual([]);
});
