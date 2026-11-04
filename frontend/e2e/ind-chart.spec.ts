import { expect, test, type Page } from "@playwright/test";
import { gauge, panel, run, setup } from "./p19util";

// IND -> GP: library indicators and formulas join the chart's wanted list; adding or removing one touches only its own series
// (no rebuild, no refetch, zoom stays). Mocked history only.

const range = async (page: Page) => ({ from: await gauge(page, "chart.visFrom"), to: await gauge(page, "chart.visTo") });

test("IND adds a library indicator and a formula to the GP chart without touching zoom, then toggles them off", async ({ page }) => {
  const { errors } = await setup(page);
  let history = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/history?")) history++;
  });
  await run(page, "AAA GP 1Y");
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(0);
  await expect.poll(() => gauge(page, "chart.panes")).toBe(1);
  // IND next to the chart (Shift+Enter = new panel; the split re-lays the chart out, so measure after it).
  await page.keyboard.press("Control+k");
  await page.keyboard.type("IND");
  await page.keyboard.press("Shift+Enter");
  const search = page.getByTestId("ind-search");
  await expect(search).toBeVisible();

  await expect.poll(() => gauge(page, "chart.panes")).toBe(1);
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(1);
  await page.keyboard.press("Alt+1"); // back to the chart for the zoom keys
  await page.keyboard.press("Escape");
  const loads = history;
  const rebuilds = await gauge(page, "chart.rebuilds");

  const before = await range(page);
  await page.keyboard.press("+");
  await page.keyboard.press("+");
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => (await range(page)).to - (await range(page)).from).toBeLessThan((before.to! - before.from!) * 0.85);
  const zoomed = await range(page);
  const same = async () => {
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(null)))));
    const r = await range(page);
    expect(Math.abs(r.from! - zoomed.from!)).toBeLessThanOrEqual(1);
    expect(Math.abs(r.to! - zoomed.to!)).toBeLessThanOrEqual(1);
    expect(await gauge(page, "chart.rebuilds")).toBe(rebuilds);
    expect(history).toBe(loads);
  };

  await page.keyboard.press("Alt+2"); // IND again (the chart is still the last GP, so it answers)
  await search.focus();
  await search.fill("aroon");
  await search.press("Enter");
  await expect(page.getByTestId("ind-msg")).toHaveText("ADDED AROON TO CHART");
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(2); // Aroon up + down
  await expect.poll(() => gauge(page, "chart.panes")).toBe(2);
  await expect(page.locator('.ind-row[data-id="AROON"]').getByTestId("ind-on")).toBeVisible();
  await same();

  await search.fill("");
  await search.press("Enter"); // the formula row
  const box = page.getByTestId("ind-formula");
  await expect(box).toBeVisible();
  await box.fill("EMA(close,12)-EMA(close,26)");
  await box.press("Enter");
  await expect(page.getByTestId("ind-msg")).toContainText("ADDED EMA(close,12)-EMA(close,");
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(3);
  await expect.poll(() => gauge(page, "chart.panes")).toBe(3);
  await same();

  // The GP panel's args hold both (what a layout saves).
  await expect(panel(page, 1).locator(".line").first()).toContainText("AROON");

  // Toggle AROON off from IND: its pane and series go.
  await box.press("Escape");
  await search.fill("aroon");
  await search.press("Enter");
  await expect(page.getByTestId("ind-msg")).toHaveText("REMOVED AROON FROM CHART");
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(1);
  await expect.poll(() => gauge(page, "chart.panes")).toBe(2);
  await expect(page.locator('.ind-row[data-id="AROON"]').getByTestId("ind-on")).toHaveCount(0);
  await same();

  expect(errors).toEqual([]);
});

test("GP takes library ids and formulas as command arguments; a broken formula shows its error and keeps the rest", async ({ page }) => {
  const { errors } = await setup(page);
  await run(page, "AAA GP ATR(14)");
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(1);
  await expect.poll(() => gauge(page, "chart.panes")).toBe(2);
  await expect(panel(page, 1).locator(".line").first()).toContainText("ATR(14)");

  await run(page, "AAA GP ATR(14) F:FOO(close)");
  await expect(page.getByTestId("gp-custom-err")).toContainText("FORMULA ERROR: UNKNOWN FUNCTION FOO");
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(1);

  await run(page, "AAA GP ATR(14) F:EMA(close,12)-EMA(close,26)");
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(2);
  await expect(page.getByTestId("gp-custom-err")).toHaveCount(0);
  expect(errors).toEqual([]);
});
