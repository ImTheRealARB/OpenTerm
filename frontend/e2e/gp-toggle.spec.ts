import { expect, test, type Page } from "@playwright/test";
import { gauge, panel, run, setup } from "./p19util";

// Indicator toggles on GP add or remove only their own series: no chart rebuild, no refetch, zoom and scroll stay.

const range = async (page: Page) => ({ from: await gauge(page, "chart.visFrom"), to: await gauge(page, "chart.visTo") });

test("GP: toggling indicators keeps zoom, scroll and the loaded bars", async ({ page }) => {
  const { errors } = await setup(page);
  let history = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/history?")) history++;
  });
  await run(page, "AAA GP 1Y");
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(0);
  await expect.poll(() => gauge(page, "chart.panes")).toBe(1);
  const loads = history;
  const rebuilds = await gauge(page, "chart.rebuilds");

  // Zoom in and scroll back, then wait until the gauge shows the new range.
  const before = await range(page);
  await page.keyboard.press("+");
  await page.keyboard.press("+");
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => (await range(page)).to - (await range(page)).from).toBeLessThan((before.to! - before.from!) * 0.8);
  await expect.poll(async () => (await range(page)).to).toBeLessThan(before.to! - 20);
  // Take the reference only once the range has settled: on a slow CI runner the last ArrowLeft was still being painted,
  // so the "zoomed" range moved 10 bars after it was read (same race as ind-chart).
  const frames = () => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(null)))));
  await expect.poll(async () => {
    const a = await range(page);
    await frames();
    const b = await range(page);
    return a.from === b.from && a.to === b.to;
  }).toBe(true);
  const zoomed = await range(page);

  const same = async () => {
    // The gauge follows a rAF after the change; give it a few frames, then compare.
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(null)))));
    const r = await range(page);
    expect(Math.abs(r.from! - zoomed.from!)).toBeLessThanOrEqual(1);
    expect(Math.abs(r.to! - zoomed.to!)).toBeLessThanOrEqual(1);
    expect(await gauge(page, "chart.rebuilds")).toBe(rebuilds);
    expect(history).toBe(loads);
  };
  const pick = async (key: string) => {
    await page.keyboard.press("i");
    await expect(panel(page).locator(".picker")).toBeVisible();
    await page.keyboard.press(key);
    await page.keyboard.press("Escape");
    await expect(panel(page).locator(".picker")).toHaveCount(0);
  };

  await pick("1"); // SMA20 (overlay)
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(1);
  await same();
  await pick("5"); // RSI (own pane)
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(2);
  await expect.poll(() => gauge(page, "chart.panes")).toBe(2);
  await same();
  await pick("6"); // MACD (second pane)
  await expect.poll(() => gauge(page, "chart.panes")).toBe(3);
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(5);
  await same();
  await pick("5"); // RSI off: its pane goes, MACD stays
  await expect.poll(() => gauge(page, "chart.panes")).toBe(2);
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(4);
  await same();
  await pick("1"); // SMA20 off
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(3);
  await pick("6"); // MACD off
  await expect.poll(() => gauge(page, "chart.panes")).toBe(1);
  await expect.poll(() => gauge(page, "chart.extraSeries")).toBe(0);
  await same();

  expect(errors).toEqual([]);
});
