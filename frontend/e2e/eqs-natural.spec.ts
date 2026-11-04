import { expect, test } from "@playwright/test";
import { openApp } from "./app";
import { env, now } from "./p19util";

// Mocked screener (made-up rows, not market data).
const UNIVERSE = {
  columns: ["symbol", "name", "last", "chg", "pct", "volume", "mcap", "country", "ipo", "sector", "industry"],
  rows: [
    ["NVDA", "NVIDIA Corp", 180, 3.6, 2.04, 200e6, 4.4e12, 1, 1999, 1, 1],
    ["AMD", "Advanced Micro Devices", 40, -2, -1.2, 50e6, 2.6e11, 1, null, 1, 1],
    ["TINY", "Tiny Software Inc", 8, 0.1, 0.5, 2e5, 5e8, 1, null, 1, 3],
    ["PFE", "Pfizer Inc", 28, 0.1, 0.36, 30e6, 1.6e11, 1, null, 2, 2],
    ["BABA", "Alibaba Group", 90, 1, 1.1, 10e6, 2.2e11, 2, 2014, 3, 4],
  ],
  sectors: ["", "Technology", "Health Care", "Consumer Discretionary"],
  industries: ["", "Semiconductors", "Biotechnology", "Software", "Catalog/Specialty Distribution"],
  countries: ["", "United States", "China"],
  count: 5, as_of_text: "Data as of Oct 16, 2026 4:15 PM ET", market: "us", source: "nasdaq_screener", as_of: now(),
};

async function setup(page: import("@playwright/test").Page) {
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/screener", (r) => r.fulfill({ json: env(UNIVERSE, { source: "nasdaq_screener" }) }));
  await openApp(page);
}
const run = async (page: import("@playwright/test").Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
};
const panel = (page: import("@playwright/test").Page) => page.locator('[data-panel="1"]');

test("EQS in English: shows the interpreted filter and filters the rows", async ({ page }) => {
  await setup(page);
  await run(page, "EQS tech stocks with price under 50");
  const p = panel(page);
  await expect(p.getByTestId("eqs-interp")).toContainText("SHOWING: SECTOR = TECHNOLOGY, PRICE < $50");
  await expect(p).toContainText("2 MATCH"); // AMD (40) and TINY (8); NVDA is 180
  await expect(p.locator(".grid .sr")).toContainText("AMD");
  await expect(p.getByTestId("eqs-interp-note")).toHaveCount(0);
});

test("EQS in English: ratios the data does not have are reported, not guessed", async ({ page }) => {
  await setup(page);
  await run(page, "EQS tech stocks with P/E under 20 and dividend yield above 2%");
  const p = panel(page);
  await expect(p.getByTestId("eqs-interp")).toContainText("SECTOR = TECHNOLOGY");
  await expect(p.getByTestId("eqs-interp-note")).toContainText("NOT IN SCREENER DATA");
  await expect(p.getByTestId("eqs-interp-note")).toContainText("P/E, DIV YIELD");
});

test("EQS in English: unknown words are listed", async ({ page }) => {
  await setup(page);
  await run(page, "EQS tech stocks that are sparkly");
  await expect(panel(page).getByTestId("eqs-interp-note")).toContainText("DID NOT UNDERSTAND: SPARKLY");
});

test("EQS with real syntax is unchanged (no interpreted line)", async ({ page }) => {
  await setup(page);
  await run(page, "EQS SECTOR=TECH PRICE<50");
  await expect(panel(page)).toContainText("2 MATCH");
  await expect(panel(page).getByTestId("eqs-interp")).toHaveCount(0);
});
