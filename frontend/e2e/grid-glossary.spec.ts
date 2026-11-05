import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";
import { env, quote } from "./p19util";

/** Glossary tips on canvas grid column headers (GUI mode only). Mocked routes, no network. */

async function setup(page: Page, mode: "terminal" | "gui") {
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => {
    const syms = new URL(r.request().url()).searchParams.get("symbols")!.split(",");
    return r.fulfill({ json: { results: Object.fromEntries(syms.map((s, i) => [s, env(quote(s, 100 + i))])) } });
  });
  await openApp(page, { mode, welcome: mode === "gui" ? false : undefined });
  await page.locator("#cmdline").fill("Q AAPL MSFT");
  await page.keyboard.press("Enter");
  await expect(page.locator(".grid .sr")).toContainText("AAPL");
}

/** Moves the mouse along the header row and returns the tip text seen at each step (the canvas has no per-header DOM). */
async function sweep(page: Page): Promise<Set<string>> {
  const box = (await page.locator(".grid canvas").first().boundingBox())!;
  const seen = new Set<string>();
  for (let x = 4; x < Math.min(box.width, 900); x += 8) {
    await page.mouse.move(box.x + x, box.y + 6);
    const tip = page.getByTestId("gl-tip");
    if (await tip.count()) seen.add(((await tip.first().getAttribute("role")) === "tooltip" ? "" : "NOROLE ") + ((await tip.first().textContent()) ?? ""));
  }
  return seen;
}

test("GUI: hovering a grid header shows the plain-English line", async ({ page }) => {
  await setup(page, "gui");
  await expect.poll(async () => [...(await sweep(page))].join("|")).toContain("VOLUME: How many shares were traded today");
  const seen = [...(await sweep(page))];
  expect(seen.some((t) => /^CHANGE: /.test(t))).toBe(true);
  expect(seen.some((t) => /^LAST: /.test(t))).toBe(true);
  // moving off the header row hides it
  const box = (await page.locator(".grid canvas").first().boundingBox())!;
  await page.mouse.move(box.x + 20, box.y + 60);
  await expect(page.getByTestId("gl-tip")).toHaveCount(0);
});

test("GUI: Shift+T steps through the glossary columns, Esc hides the tip", async ({ page }) => {
  await setup(page, "gui");
  await page.keyboard.press("Escape");
  await expect(async () => {
    await page.keyboard.press("Shift+T");
    await expect(page.getByTestId("gl-tip")).toBeVisible({ timeout: 500 });
  }).toPass();
  const first = await page.getByTestId("gl-tip").textContent();
  await page.keyboard.press("Shift+T");
  await expect.poll(async () => await page.getByTestId("gl-tip").textContent()).not.toBe(first);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("gl-tip")).toHaveCount(0);
});

test("Terminal: no header tooltip", async ({ page }) => {
  await setup(page, "terminal");
  expect((await sweep(page)).size).toBe(0);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Shift+T");
  await page.waitForTimeout(300);
  await expect(page.getByTestId("gl-tip")).toHaveCount(0);
});
