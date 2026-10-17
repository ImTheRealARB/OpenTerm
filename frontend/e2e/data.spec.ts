import { expect, test } from "@playwright/test";

const env = (data: unknown, source = "yahoo") => ({ data, source, as_of: 0, age_s: 0, stale: false, fallback_from: [] });

test.beforeEach(async ({ page }) => {
  await page.route("**/api/search?**", (r) =>
    r.fulfill({
      json: env([{ symbol: "RELIANCE.NS", name: "Reliance Industries Limited", exchange: "NSE", type: "Equity", source: "yahoo" }]),
    }),
  );
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
});

test("ticker search suggests securities and prefetches the highlighted one", async ({ page }) => {
  const prefetched: string[] = [];
  await page.route("**/api/history?**", (r) => {
    prefetched.push(r.request().url());
    return r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable" } });
  });
  await page.route("**/api/quote?**", (r) => r.fulfill({ json: { results: {} } }));
  await page.keyboard.press("Control+k");
  await page.keyboard.type("relian");
  await expect(page.locator(".ac")).toContainText("RELIANCE.NS");
  await expect(page.locator(".ac")).toContainText("NSE");
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => prefetched.some((u) => u.includes("symbol=RELIANCE.NS"))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(page.locator("#cmdline")).toHaveValue("RELIANCE.NS ");
});

test("SOURCES shows provider health and key requirements", async ({ page }) => {
  await page.route("**/api/sources", (r) =>
    r.fulfill({
      json: {
        providers: [
          { name: "yahoo", label: "Yahoo", source: "yahoo", capabilities: ["quotes"], markets: "Global", terms: "Unofficial",
            status: "DOWN", down_for_s: 42, latency_p50_ms: 230, latency_p95_ms: 600, calls: 9, errors: 3,
            last_error: "rate_limited: 429", last_error_age_s: 5, last_ok_age_s: 60, tokens_remaining: 0, rate_per_s: 4 },
          { name: "nasdaq", label: "Nasdaq", source: "nasdaq", capabilities: ["quotes"], markets: "US", terms: "Public",
            status: "OK", down_for_s: 0, latency_p50_ms: 300, latency_p95_ms: 400, calls: 3, errors: 0,
            last_error: null, last_error_age_s: null, last_ok_age_s: 2, tokens_remaining: 3, rate_per_s: 2 },
        ],
        keyed: [{ name: "fred", status: "KEY REQUIRED", note: "Set FRED_API_KEY in .env." }],
        order: { quotes: ["yahoo", "nasdaq"] },
        cache: { fresh_hits: 1, stale_hits: 0, misses: 1, hit_pct: 50, inflight: 0, mem_entries: 2 },
        fixtures: false,
      },
    }),
  );
  await page.keyboard.press("Control+k");
  await page.keyboard.type("SOURCES");
  await page.keyboard.press("Enter");
  const panel = page.locator('[data-panel="1"]');
  await expect(panel).toContainText("DOWN 42S");
  await expect(panel).toContainText("rate_limited: 429");
  await expect(panel).toContainText("KEY REQUIRED");
  await expect(panel).toContainText("YAHOO → NASDAQ");
  await expect(page.locator(".status")).toContainText("YAHOO DOWN");
});
