import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";
import { bars, env, quote } from "./p19util";

/**
 * UI parity pass, brief A: light-grey tab strip with a function badge, grouped command-line suggestions with "More ..." rows,
 * the GUI "Related functions" button, and the "?" help button on every panel title bar. Mocked routes only (no network).
 */

async function setup(page: Page, hits: { symbol: string; name: string }[] = []) {
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
  await page.route("**/api/history?**", (r) => {
    const u = new URL(r.request().url());
    return r.fulfill({ json: env(bars(u.searchParams.get("symbol")!, u.searchParams.get("range") ?? "", u.searchParams.get("interval") ?? "")) });
  });
  await page.route("**/api/search?**", (r) =>
    r.fulfill({ json: env(hits.map((h) => ({ ...h, exchange: "NMS", type: "Equity", source: "yahoo" }))) }),
  );
}

/** GUI: type a command into the always-visible command line and press Enter. */
async function guiRun(page: Page, text: string) {
  const box = page.locator("#cmdline");
  await box.click();
  await box.fill(text);
  await page.keyboard.press("Enter");
}

/** Terminal: Ctrl+K focuses the command line. */
async function termRun(page: Page, text: string) {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
}

test("tab strip: light-grey chrome token, active tab shows the function badge", async ({ page }) => {
  await setup(page);
  await openApp(page, { mode: "gui", tabs: true });
  await guiRun(page, "AAPL GP");
  const strip = page.getByTestId("tab-strip");
  await expect(strip).toBeVisible();
  // The active tab: a small bold function badge before the title (the ticker, since GP uses one).
  const active = strip.locator(".gt-tab.on");
  await expect(active.getByTestId("tab-fn")).toHaveText("GP");
  await expect(active).toContainText("AAPL");
  // The strip paints with the chrome token (#e6e6e6), not the dark bar colour.
  const bg = await strip.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).toBe("rgb(230, 230, 230)");
  // Light theme: the strip keeps a visible edge (its own border colour) so it does not vanish into the white body.
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  const edge = await strip.evaluate((el) => getComputedStyle(el).borderBottomColor);
  expect(edge).not.toBe("rgb(230, 230, 230)");
});

test("suggestions are grouped; headers are skipped by ArrowDown; More rows expand a group", async ({ page }) => {
  // Six security hits: the SECURITIES group shows 4 and offers "More Securities...".
  const hits = ["DELL", "DIS", "DAL", "DASH", "DDOG", "DKNG"].map((symbol) => ({ symbol, name: `${symbol} Inc` }));
  await setup(page, hits);
  await openApp(page);
  await page.keyboard.press("Control+k");
  await page.keyboard.type("D");
  const ac = page.locator(".ac");
  await expect(ac.locator(".ac-h", { hasText: "FUNCTIONS" })).toBeVisible();
  await expect(ac.locator(".ac-h", { hasText: "SECURITIES" })).toBeVisible();
  await expect(ac.getByText("More Securities...")).toBeVisible();
  // ArrowDown lands only on options, never on a header, all the way down the list.
  const total = await ac.getByRole("option").count();
  for (let i = 0; i < total; i++) {
    await page.keyboard.press("ArrowDown");
    await expect(ac.locator(".on")).toHaveCount(1);
    await expect(ac.locator(".on")).toHaveAttribute("role", "option");
    await expect(ac.locator(".ac-h.on")).toHaveCount(0);
  }
  // The last row is the More row; Enter shows the next page and does not run the typed text.
  await expect(ac.locator(".on")).toContainText("More Securities...");
  await page.keyboard.press("Enter");
  await expect(ac.getByText("DKNG", { exact: true })).toBeVisible();
  await expect(ac.getByText("More Securities...")).toHaveCount(0);
  await expect(page.locator("#cmdline")).toHaveValue("D");
});

test("Related functions button opens the RELATED menu; a number runs that function on the same security", async ({ page }) => {
  await setup(page);
  await openApp(page, { mode: "gui" });
  await guiRun(page, "AAPL DES");
  const head = page.locator('[data-panel="1"] .ph');
  await expect(head).toContainText("AAPL");
  await page.getByTestId("related-btn").click();
  const menu = page.getByTestId("window-menu");
  await expect(menu).toContainText("1)");
  await expect(menu).toContainText("2)");
  // Item 1 is GP and item 2 is QR (DES itself is left out): pressing 2 runs QR on AAPL.
  await page.keyboard.press("2");
  await expect(menu).toHaveCount(0);
  await expect(head).toContainText("AAPL | QR");
});

test("Terminal: the ? button on a panel title bar shows HELP for that function", async ({ page }) => {
  await setup(page);
  await openApp(page);
  await termRun(page, "AAPL GP");
  await expect(page.locator('[data-panel="1"] .ph')).toContainText("AAPL | GP");
  const help = page.getByTestId("panel-help");
  await expect(help).toHaveAttribute("aria-label", "Help for GP");
  await help.click();
  await expect(page.locator('[data-panel="1"]')).toContainText("GP — PRICE CHART");
});

test("GUI: the ? button opens the help drawer for that panel's function", async ({ page }) => {
  await setup(page);
  await openApp(page, { mode: "gui" });
  await guiRun(page, "AAPL DES");
  await expect(page.locator('[data-panel="1"] .ph')).toContainText("DES");
  await page.getByTestId("panel-help").click();
  const drawer = page.getByTestId("help-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("DES");
});
