/**
 * A paid SSE stream (SWARM here, AI uses the same helper) must be aborted when its panel is CLOSED,
 * but must keep running when the panel is only maximized/restored (that remounts the React component).
 * The mocked /api/ai/swarm never answers, so the run stays "running"; a fetch wrapper counts abort signals.
 */
import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

async function setup(page: Page) {
  // Count abort events on any fetch to /api/ai/ (the page cannot otherwise tell us a hanging request was cancelled).
  await page.addInitScript(() => {
    const w = window as unknown as { __aborts: number; __ai: number };
    w.__aborts = 0;
    w.__ai = 0;
    const real = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (url.includes("/api/ai/swarm") && init?.method === "POST") {
        w.__ai++;
        init.signal?.addEventListener("abort", () => w.__aborts++);
      }
      return real(input, init);
    };
  });
  await page.routeWebSocket(/\/ws$/, (route) =>
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    }),
  );
  await page.route("**/api/llm/health", (r) => r.fulfill({ json: { providers: [], spend: { today: 0, cap: 1 } } }));
  await page.route("**/api/ai/swarm/presets", (r) => r.fulfill({ json: { presets: [] } }));
  await page.route("**/api/ai/runs?**", (r) => r.fulfill({ json: { runs: [] } }));
  await page.route("**/api/ai/swarm", () => {
    /* never answered: the stream stays open until the page aborts it */
  });
  await openApp(page);
}

const counts = (page: Page) => page.evaluate(() => ({ ai: (window as never as { __ai: number }).__ai, aborts: (window as never as { __aborts: number }).__aborts }));

test("maximize keeps a running SWARM stream, closing the panel aborts it", async ({ page }) => {
  await setup(page);
  await page.keyboard.press("Control+\\"); // two panels, so closing one is a real close
  await page.keyboard.press("Control+k");
  await page.keyboard.type("SWARM COMMITTEE AAPL");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("swarm-panel")).toBeVisible();
  await expect.poll(async () => (await counts(page)).ai).toBe(1);

  // Maximize and restore remount the panel: the stream must not be aborted.
  await page.keyboard.press("Control+Shift+F");
  await page.waitForTimeout(300);
  await page.keyboard.press("Control+Shift+F");
  await page.waitForTimeout(300);
  expect((await counts(page)).aborts).toBe(0);

  // Closing the panel aborts it.
  await page.keyboard.press("Alt+w");
  await expect.poll(async () => (await counts(page)).aborts).toBe(1);
});

test("a second SWARM command in the same panel aborts the first run (view replaced, same function)", async ({ page }) => {
  await setup(page);
  await page.keyboard.press("Control+k");
  await page.keyboard.type("SWARM COMMITTEE AAPL");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("swarm-panel")).toBeVisible();
  await expect.poll(async () => (await counts(page)).ai).toBe(1);
  expect((await counts(page)).aborts).toBe(0); // the panel clearing its own args must not look like leaving

  await page.keyboard.press("Control+k");
  await page.keyboard.type("SWARM COMMITTEE MSFT");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await counts(page)).ai).toBe(2);
  await expect.poll(async () => (await counts(page)).aborts).toBe(1); // only the first run was cut
});
