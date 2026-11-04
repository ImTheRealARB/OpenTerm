import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";
import { bars, env, quote } from "./p19util";

/**
 * GUI mode, step B: panel toolbars, the "?" help drawer, the banner, the welcome card and the tour.
 * Mocked routes only (no network). `openApp` treats the welcome card as already seen unless a test passes `welcome: true`.
 */

async function setup(page: Page, opts: { mode?: "terminal" | "gui"; welcome?: boolean } = {}) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
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
  await openApp(page, { mode: opts.mode ?? "gui", welcome: opts.welcome });
  return { errors };
}

const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
/** Runs a command through the sidebar search box (same job as the command line). */
const run = async (page: Page, text: string) => {
  await page.getByTestId("gui-search").fill(text);
  await page.getByTestId("gui-search").press("Enter");
};

test("GP toolbar: a range button changes the range, like pressing the number key", async ({ page }) => {
  const { errors } = await setup(page);
  const ranges: string[] = [];
  page.on("request", (r) => r.url().includes("/api/history") && ranges.push(new URL(r.url()).searchParams.get("range") ?? ""));
  await run(page, "AAPL GP");
  const p = panel(page);
  await expect(p.locator(".chart canvas").first()).toBeVisible();
  await expect(p.locator(".line").first()).toContainText("AAPL 1Y");
  const bar = p.locator(".pt");
  await expect(bar.getByRole("button", { name: "5D", exact: true })).toBeVisible();
  // The chart's key handler registers when its module has loaded; clicking again until it answers is harmless.
  await expect(async () => {
    await bar.getByRole("button", { name: "5D", exact: true }).click();
    await expect(p.locator(".line").first()).toContainText("AAPL 5D", { timeout: 500 });
  }).toPass();
  expect(ranges).toContain("5D");
  // The generic buttons are there too.
  for (const name of ["CSV", "Refresh", "Max"]) await expect(bar.getByRole("button", { name, exact: true })).toBeVisible();
  await expect(bar.locator(".pt-help")).toHaveText("?"); // the two icon-like buttons carry an aria-label, so find them by class
  await expect(bar.locator(".pt-close")).toHaveText("Close");
  expect(errors).toEqual([]);
});

test("generic toolbar buttons: Max toggles to Restore", async ({ page }) => {
  await setup(page);
  const bar = panel(page).locator(".pt");
  await bar.getByRole("button", { name: "Max", exact: true }).click();
  await expect(bar.getByRole("button", { name: "Restore", exact: true })).toBeVisible();
  await bar.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(bar.getByRole("button", { name: "Max", exact: true })).toBeVisible();
});

test("WL toolbar: Add opens an inline prompt, Esc cancels it", async ({ page }) => {
  await setup(page);
  await run(page, "WL TECH");
  const bar = panel(page).locator(".pt");
  await bar.getByRole("button", { name: "Add", exact: true }).click();
  const ask = page.getByTestId("pt-ask");
  await expect(ask).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(ask).toHaveCount(0);
  await expect(page.locator(".cmd input")).toBeFocused();
});

test("? opens the help drawer for the panel's function; Esc closes it and returns focus to the ? button", async ({ page }) => {
  await setup(page);
  await run(page, "AAPL GP");
  const p = panel(page);
  await expect(p.locator(".chart canvas").first()).toBeVisible();
  const help = p.locator(".pt-help");
  await help.click();
  const drawer = page.getByTestId("help-drawer");
  await expect(drawer).toBeVisible();
  await expect(page.getByTestId("help-title")).toContainText("GP");
  await expect(page.getByTestId("help-title")).toContainText("Price chart");
  await expect(drawer).toContainText("Category: Charts");
  await expect(drawer).toContainText("Range 1 day"); // a toolbar button's description
  await expect(drawer).toContainText("Related functions");
  await expect(drawer).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(help).toBeFocused();
});

test("Alt+H opens and closes the drawer from the keyboard; terminal mode says it is a GUI feature", async ({ page }) => {
  await setup(page);
  await run(page, "AAPL GP");
  await page.keyboard.press("Alt+h");
  await expect(page.getByTestId("help-drawer")).toBeVisible();
  await page.keyboard.press("Alt+h");
  await expect(page.getByTestId("help-drawer")).toHaveCount(0);
  await page.keyboard.press("Alt+g"); // to terminal
  await expect(page.locator("html")).toHaveAttribute("data-mode", "terminal");
  await page.keyboard.press("Alt+h");
  await expect(page.locator(".msg")).toContainText("HELP DRAWER IS A GUI MODE FEATURE");
  await expect(page.getByTestId("help-drawer")).toHaveCount(0);
});

test("terminal mode shows no toolbar, banner, drawer or welcome card", async ({ page }) => {
  await setup(page, { mode: "terminal", welcome: true });
  await expect(page.locator(".pt")).toHaveCount(0);
  await expect(page.getByTestId("gui-banner")).toHaveCount(0);
  await expect(page.getByTestId("help-drawer")).toHaveCount(0);
  await expect(page.getByTestId("welcome-card")).toHaveCount(0);
});

test("banner: the x dismisses it for good (survives a reload); Switch now goes to terminal", async ({ page }) => {
  await setup(page);
  const banner = page.getByTestId("gui-banner");
  await expect(banner).toContainText("Switch to Terminal mode for keyboard speed");
  await page.getByTestId("gui-banner-close").click();
  await expect(banner).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("openterm.guiBanner"))).not.toBeNull();
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  await expect(page.getByTestId("gui-menubar")).toBeVisible();
  await expect(banner).toHaveCount(0);
});

test("banner: Switch now switches to terminal mode", async ({ page }) => {
  await setup(page);
  await page.getByTestId("gui-banner-switch").click();
  await expect(page.locator("html")).toHaveAttribute("data-mode", "terminal");
  await expect(page.getByTestId("gui-banner")).toHaveCount(0);
});

test("welcome card: shows on a first run, 'See a chart' opens GP for AAPL, and it does not come back after a reload", async ({ page }) => {
  await setup(page, { welcome: true });
  const card = page.getByTestId("welcome-card");
  await expect(card).toBeVisible();
  await expect(page.getByTestId("welcome-des")).toBeFocused(); // keyboard users can press Enter at once
  await page.getByTestId("welcome-gp").click();
  await expect(card).toHaveCount(0);
  await expect(panel(page).locator(".ph")).toContainText("GP");
  await expect(panel(page).locator(".ph")).toContainText("AAPL");
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  await expect(page.getByTestId("gui-menubar")).toBeVisible();
  await expect(card).toHaveCount(0);
});

test("welcome card: Tab reaches the buttons, Enter on 'Look up a stock' opens DES, Esc closes", async ({ page }) => {
  await setup(page, { welcome: true });
  const card = page.getByTestId("welcome-card");
  // The card is a lazy chunk now (loaded right after first paint), so wait until it is on screen before using Tab.
  await expect(card).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("welcome-gp")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByTestId("welcome-des")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(card).toHaveCount(0);
  await expect(panel(page).locator(".ph")).toContainText("DES");
});

test("welcome card: Esc closes it and the command line gets the keyboard", async ({ page }) => {
  await setup(page, { welcome: true });
  await expect(page.getByTestId("welcome-card")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("welcome-card")).toHaveCount(0);
  await expect(page.locator(".cmd input")).toBeFocused();
});

test("tour: Take the tour walks through every step, Back works, Done ends it", async ({ page }) => {
  await setup(page, { welcome: true });
  await page.getByTestId("welcome-tour").click();
  await expect(page.getByTestId("welcome-card")).toHaveCount(0);
  const cap = page.getByTestId("tour-caption");
  await expect(cap).toContainText("STEP 1 OF 5");
  await expect(cap).toContainText("Menu bar");
  await expect(page.getByTestId("tour-ring")).toBeVisible();
  await expect(page.getByTestId("tour-back")).toBeDisabled();
  await page.keyboard.press("Enter"); // focus sits on Next
  await expect(cap).toContainText("STEP 2 OF 5");
  await expect(cap).toContainText("Sidebar");
  await page.getByTestId("tour-next").click();
  await expect(cap).toContainText("Symbol box");
  await page.getByTestId("tour-back").click();
  await expect(cap).toContainText("STEP 2 OF 5");
  await page.getByTestId("tour-next").click();
  await page.getByTestId("tour-next").click();
  await expect(cap).toContainText("Mode switch");
  await page.getByTestId("tour-next").click();
  await expect(cap).toContainText("STEP 5 OF 5");
  await expect(cap).toContainText("Panel buttons");
  // The ring surrounds the panel's ? button.
  const ring = await page.getByTestId("tour-ring").boundingBox();
  const help = await panel(page).locator(".pt-help").boundingBox();
  expect(ring && help && ring.x <= help.x && ring.y <= help.y && ring.x + ring.width >= help.x + help.width).toBe(true);
  await expect(page.getByTestId("tour-next")).toHaveText("Done");
  await page.getByTestId("tour-next").click();
  await expect(cap).toHaveCount(0);
  await expect(page.getByTestId("tour-ring")).toHaveCount(0);
});

test("tour: Esc ends it; it can be replayed from Settings > Take the tour", async ({ page }) => {
  await setup(page);
  await expect(page.getByTestId("tour-caption")).toHaveCount(0);
  const bar = page.getByTestId("gui-menubar");
  await bar.locator(".gm-cat", { hasText: "Settings" }).click();
  await bar.locator('.gm-item:has-text("Take the tour")').click();
  await expect(page.getByTestId("tour-caption")).toContainText("STEP 1 OF 5");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("tour-caption")).toHaveCount(0);
  await expect(page.locator(".cmd input")).toBeFocused();
  // And the welcome card from the same menu.
  await bar.locator(".gm-cat", { hasText: "Settings" }).click();
  await bar.locator('.gm-item:has-text("Show welcome card")').click();
  await expect(page.getByTestId("welcome-card")).toBeVisible();
});

test("HELP panel has the tour and welcome links in GUI mode only", async ({ page }) => {
  await setup(page);
  await run(page, "HELP");
  await expect(panel(page).getByTestId("help-gui-line")).toContainText("Take the tour");
  await panel(page).getByRole("button", { name: "Take the tour" }).click();
  await expect(page.getByTestId("tour-caption")).toContainText("STEP 1 OF 5");
});

test("SETTINGS panel: the INTERFACE MODE row switches the mode", async ({ page }) => {
  await setup(page);
  await run(page, "SETTINGS");
  const row = panel(page).locator("tr.on");
  await expect(row).toContainText("THEME");
  // Panel keys register after the module loads: retry J until the cursor leaves THEME, then go back to the top.
  await expect(async () => {
    await page.keyboard.press("Escape"); // an early "j" would type into the command line
    await page.keyboard.press("j");
    await expect(row).not.toHaveAttribute("data-row", "theme", { timeout: 250 });
  }).toPass();
  await page.keyboard.press("g");
  await expect(row).toHaveAttribute("data-row", "theme");
  // MODE is the last of the 15 setting rows: 14 steps down.
  for (let i = 0; i < 14; i++) await page.keyboard.press("j");
  await expect(row).toHaveAttribute("data-row", "mode");
  await expect(panel(page).locator("tr[data-row='mode']")).toContainText("GUI");
  await page.keyboard.press("l");
  await expect(page.locator("html")).toHaveAttribute("data-mode", "terminal");
  await expect(panel(page).locator("tr[data-row='mode']")).toContainText("TERMINAL");
});
