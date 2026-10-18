import { expect, test, type Page } from "@playwright/test";
import { env, gauge, now, panel, run, setup } from "./p19util";

// Phase 19 step 3 end-to-end tests (mocked routes only): IMAP and GIP.

const UNIVERSE = {
  columns: ["symbol", "name", "last", "chg", "pct", "volume", "mcap", "country", "ipo", "sector", "industry"],
  rows: [
    ["NVDA", "NVIDIA Corp", 180, 3.6, 2.04, 200e6, 4.4e12, 1, 1999, 1, 1],
    ["AMD", "Advanced Micro Devices", 160, -2, -1.2, 50e6, 2.6e11, 1, null, 1, 1],
    ["PFE", "Pfizer Inc", 28, 0.1, 0.36, 30e6, 1.6e11, 1, null, 2, 2],
    ["BABA", "Alibaba Group", 90, 1, 1.1, 10e6, 2.2e11, 2, 2014, 3, 3],
    ["NOCAP", "No Cap Inc", 5, 0, 0, 1e6, null, 1, null, 1, 1],
  ],
  sectors: ["", "Technology", "Health Care", "Consumer Discretionary"],
  industries: ["", "Semiconductors", "Biotechnology", "Catalog/Specialty Distribution"],
  countries: ["", "United States", "China"],
  count: 5, as_of_text: "Data as of Oct 16, 2026 4:15 PM ET", market: "us", source: "nasdaq_screener", as_of: now(),
};

async function setupImap(page: Page) {
  const base = await setup(page);
  await page.route("**/api/screener", (r) => r.fulfill({ json: env(UNIVERSE, { source: "nasdaq_screener" }) }));
  return base;
}

test("IMAP: tiles by sector sized by market cap, keyboard moves, zoom into a group, Enter opens Q", async ({ page }) => {
  const { errors } = await setupImap(page);
  await run(page, "IMAP");
  const p = panel(page);
  await expect(p).toContainText("IMAP SECTOR");
  await expect(p).toContainText("SIZE = MARKET CAP");
  await expect(p).toContainText("1 ROWS WITHOUT A MARKET CAP HAVE NO TILE");
  await expect(p.getByTestId("imap-canvas")).toBeVisible();
  await expect.poll(() => gauge(page, "imap.tiles")).toBe(4);
  await expect(p.locator(".sr")).toContainText("NVDA NVIDIA Corp +2.04%");
  await expect(p.locator(".sr")).toContainText("TECHNOLOGY");
  await expect.poll(() => gauge(page, "imap.paintMs")).toBeGreaterThanOrEqual(0);

  // The biggest tile is selected first; moving along the layout reaches the others.
  const seen = new Set<string>();
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press(["j", "l", "k", "h", "j", "l"][i]);
    seen.add((await p.locator(".sr").textContent())!.split(" ")[0]);
  }
  expect(seen.size).toBeGreaterThanOrEqual(2);

  await page.keyboard.press("z");
  await expect(p).toContainText("IMAP SECTOR >");
  const zoomed = (await gauge(page, "imap.tiles")) as number;
  expect(zoomed).toBeLessThan(4);
  await page.keyboard.press("Backspace");
  await expect.poll(() => gauge(page, "imap.tiles")).toBe(4);

  await page.keyboard.press("Enter");
  await expect(p.locator(".ph")).toContainText("Q");
  expect(errors).toEqual([]);
});

test("IMAP: grouping words, EQS filter tokens and N=", async ({ page }) => {
  await setupImap(page);
  await run(page, "IMAP COUNTRY MCAP>200B");
  await expect(panel(page)).toContainText("IMAP COUNTRY · MCAP>200B");
  await expect.poll(() => gauge(page, "imap.tiles")).toBe(3);
  await run(page, "IMAP N=2");
  await expect(panel(page)).toContainText("2 SMALLEST NOT SHOWN (N=2");
  await expect.poll(() => gauge(page, "imap.tiles")).toBe(2);
  await run(page, "IMAP MCAP>100T");
  await expect(panel(page)).toContainText("NO ROWS MATCH THIS FILTER");
});

test("IMAP: a failing screener says so and F5 retries", async ({ page }) => {
  await setup(page);
  let calls = 0;
  await page.route("**/api/screener", (r) => {
    calls++;
    return calls === 1
      ? r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "nasdaq_screener: 503" } })
      : r.fulfill({ json: env(UNIVERSE, { source: "nasdaq_screener" }) });
  });
  await run(page, "IMAP");
  await expect(panel(page)).toContainText("PROVIDER DOWN");
  await expect(panel(page)).toContainText("F5 TO RETRY");
  await page.keyboard.press("F5");
  await expect.poll(() => gauge(page, "imap.tiles")).toBe(4);
});

// --- GIP ---
const tickBars = (n: number, barS: number, extra: Record<string, unknown> = {}) => {
  const t0 = Math.floor(now() / barS) * barS - n * barS;
  const t = Array.from({ length: n }, (_, i) => t0 + i * barS);
  const c = t.map((_, i) => 100 + Math.sin(i / 5));
  return {
    symbol: "AAA", bar_s: barS, ticks: n * 3, since_ms: t[0] * 1000, last_ms: t[n - 1] * 1000, synthetic: false, sessions: 1, source_code: "y",
    t, o: c, h: c.map((x) => x + 0.2), l: c.map((x) => x - 0.2), c, v: null, ...extra,
  };
};

test("GIP: bars from the tick buffer, labelled with since-when, S cycles the bar size", async ({ page }) => {
  await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/ticks/**", (r) => {
    const u = new URL(r.request().url());
    const bar = u.searchParams.get("bar")!;
    asked.push(bar);
    const secs = { "1s": 1, "5s": 5, "15s": 15, "1m": 60 }[bar]!;
    return r.fulfill({ json: env(tickBars(120, secs), { source: "TICKS · YAHOO STREAM" }) });
  });
  await run(page, "AAA GIP");
  const p = panel(page);
  await expect(p).toContainText("GIP AAA 5S TICK BARS");
  await expect(p).toContainText("360 TICKS SINCE");
  await expect(p).toContainText("TICKS · YAHOO STREAM");
  await expect(p).toContainText("NOT FROM THE EXCHANGE");
  await expect(p).toContainText("NO TICK VOLUME FROM THIS SOURCE");
  await expect.poll(() => gauge(page, "chart.drawSegs")).toBeDefined();
  await page.keyboard.press("s");
  await expect(p).toContainText("GIP AAA 15S TICK BARS");
  expect(asked).toEqual(["5s", "15s"]);
});

test("GIP: no ticks says so, never draws a chart; synthetic data is labelled", async ({ page }) => {
  await setup(page);
  let mode: "empty" | "syn" = "empty";
  await page.route("**/api/world/ticks/**", (r) =>
    r.fulfill({
      json:
        mode === "empty"
          ? env({ symbol: "AAA", bar_s: 5, ticks: 0, since_ms: null, last_ms: null, synthetic: false, sessions: 0, source_code: null, t: [], o: [], h: [], l: [], c: [], v: null }, { source: "TICKS (NONE SEEN YET)" })
          : env(tickBars(60, 5, { synthetic: true, source_code: "s" }), { source: "TICKS · SYNTHETIC" }),
    }),
  );
  await run(page, "AAA GIP");
  await expect(panel(page)).toContainText("NO TICKS SINCE OPEN");
  await expect(panel(page).locator(".chart")).toHaveCount(0);
  mode = "syn";
  await page.keyboard.press("F5");
  await expect(panel(page)).toContainText("SYNTHETIC TEST DATA, NOT A SECURITY");
  await expect(panel(page).locator(".chart")).toHaveCount(1);
});

test("GIP: an error is shown with a retry hint", async ({ page }) => {
  await setup(page);
  await page.route("**/api/world/ticks/**", (r) => r.fulfill({ status: 400, json: { error: "BAD SYMBOL: X", kind: "bad_request" } }));
  await run(page, "AAA GIP");
  await expect(panel(page)).toContainText("BAD SYMBOL: X");
  await expect(panel(page)).toContainText("F5 TO RETRY");
});

test("PERF CALC: IMAP gauges are published", async ({ page }) => {
  await setup(page);
  await run(page, "PERF CALC");
  await expect.poll(() => gauge(page, "p19.treemapMs")).toBeLessThan(1000);
  await expect.poll(() => gauge(page, "p19.imapPaintMs")).toBeLessThan(1000);
});
