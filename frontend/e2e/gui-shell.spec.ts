import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";
import { bars, env, quote } from "./p19util";

/**
 * GUI mode, step A: menu bar, sidebar, symbol box, status-bar mode switch. Mocked routes only (no network).
 * Every other spec runs in terminal mode (openApp's default); these tests ask for the GUI shell with { mode: "gui" }.
 */

async function setupGui(page: Page, opts: { statusBar?: boolean } = {}) {
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
  await openApp(page, { mode: "gui", statusBar: opts.statusBar });
  return { errors };
}

test("the bottom status bar is hidden by default in GUI mode; Settings > Status toggles it, Settings > Font switches the font", async ({ page }) => {
  await setupGui(page, { statusBar: false });
  await expect(page.getByTestId("mode-gui")).toHaveCount(0); // the mode switch lives in the status bar
  const settingsMenu = () => page.locator('.gm-cat[data-cat="Settings"]').click();
  await settingsMenu();
  await page.getByTestId("statusbar-toggle").click();
  await expect(page.getByTestId("mode-gui")).toBeVisible();
  await settingsMenu();
  await page.getByTestId("statusbar-toggle").click();
  await expect(page.getByTestId("mode-gui")).toHaveCount(0);
  // Font: the dropdown sits inside the Settings menu; a bundled preset sets the CSS variable at once.
  await settingsMenu();
  await page.getByTestId("font-select").selectOption("Geist Mono");
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--font"))).toContain("Geist Mono");
  await settingsMenu();
  await page.getByTestId("font-select").selectOption("");
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--font"))).not.toContain("Geist Mono");
});

const header = (page: Page) => page.locator('[data-panel="1"] .ph');

test("a fresh GUI shows the menu bar and the sidebar, and no page errors", async ({ page }) => {
  const { errors } = await setupGui(page);
  await expect(page.locator("html")).toHaveAttribute("data-mode", "gui");
  const bar = page.getByTestId("gui-menubar");
  await expect(bar).toBeVisible();
  await expect(bar.locator(".gm-cat")).toHaveText(["Markets", "Charts", "News", "Research", "Portfolio", "Backtest", "Settings"]);
  await expect(page.getByTestId("gui-sidebar")).toBeVisible();
  await expect(page.getByTestId("gui-sidebar").locator(".gs-head")).toHaveCount(7);
  // The command line, workspace and status bar are still there.
  await expect(page.locator(".cmd input")).toBeVisible();
  await expect(page.locator('[data-panel="1"]')).toBeVisible();
  await expect(page.getByTestId("mode-gui")).toHaveAttribute("aria-pressed", "true");
  expect(errors).toEqual([]);
});

test("command line: GP + Enter opens the chart in the focused panel", async ({ page }) => {
  await setupGui(page);
  // GP needs a security: the symbol box loads one first (same as typing AAPL on the command line).
  await page.getByTestId("gui-symbol").fill("AAPL");
  await page.getByTestId("gui-symbol").press("Enter");
  await expect(header(page)).toContainText("AAPL");
  await page.locator("#cmdline").fill("GP");
  await page.locator("#cmdline").press("Enter");
  await expect(header(page)).toContainText("GP");
  await expect(header(page)).toContainText("AAPL");
});

test("symbol box keeps the panel's function: GP of AAPL becomes GP of MSFT", async ({ page }) => {
  await setupGui(page);
  await page.locator("#cmdline").fill("AAPL GP");
  await page.locator("#cmdline").press("Enter");
  await expect(header(page)).toContainText("GP");
  await page.getByTestId("gui-symbol").fill("MSFT");
  await page.getByTestId("gui-symbol").press("Enter");
  await expect(header(page)).toContainText("MSFT");
  await expect(header(page)).toContainText("GP");
});

test("sidebar: clicking a row runs it, groups collapse, a bad command shows the command line's error", async ({ page }) => {
  await setupGui(page);
  const side = page.getByTestId("gui-sidebar");
  // News starts collapsed: expand it, then click N.
  const news = side.locator(".gs-head", { hasText: "News" });
  await expect(news).toHaveAttribute("aria-expanded", "false");
  await news.click();
  await expect(news).toHaveAttribute("aria-expanded", "true");
  await side.locator('.gs-item[data-code="N"]').click();
  await expect(header(page)).toContainText("N");
  await expect(header(page)).not.toContainText("NO FUNCTION");
  await news.click();
  await expect(news).toHaveAttribute("aria-expanded", "false");
  // GP without any security: the same error the command line gives.
  await page.locator("#cmdline").fill("GP");
  await page.locator("#cmdline").press("Enter");
  await expect(page.locator(".msg")).toContainText("GP NEEDS A SECURITY");
});

test("menu bar: a category opens its functions and picking one runs it; Esc closes and returns to the command line", async ({ page }) => {
  await setupGui(page);
  const bar = page.getByTestId("gui-menubar");
  await bar.locator(".gm-cat", { hasText: "Settings" }).click();
  const drop = bar.locator(".gm-drop");
  await expect(drop).toBeVisible();
  await expect(drop.locator(".gm-item", { hasText: "Switch to Terminal mode" })).toBeVisible();
  await drop.locator('.gm-item:has-text("Keyboard shortcuts")').click();
  await expect(drop).toHaveCount(0);
  await expect(header(page)).toContainText("SHORTCUTS");
  // Keyboard: Tab-reachable category, Enter opens and focuses the first item, Esc closes and focuses the command line.
  await bar.locator(".gm-cat", { hasText: "Markets" }).focus();
  await page.keyboard.press("Enter");
  await expect(bar.locator(".gm-drop")).toBeVisible();
  await expect(bar.locator(".gm-item").first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(bar.locator(".gm-drop")).toHaveCount(0);
  await expect(page.locator(".cmd input")).toBeFocused();
});

test("Esc in the symbol box returns to the command line; Ctrl+K still works from it", async ({ page }) => {
  await setupGui(page);
  await page.getByTestId("gui-symbol").focus();
  await page.keyboard.type("chart");
  await page.keyboard.press("Escape");
  await expect(page.locator(".cmd input")).toBeFocused();
  await page.getByTestId("gui-symbol").focus();
  await page.keyboard.press("Control+k"); // chords bubble past the box to the global handler
  await expect(page.locator(".cmd input")).toBeFocused();
});

test("the status-bar switch goes to terminal (the GUI shell disappears) and the mode survives a reload", async ({ page }) => {
  await setupGui(page);
  await page.getByTestId("mode-terminal").click();
  await expect(page.locator("html")).toHaveAttribute("data-mode", "terminal");
  await expect(page.getByTestId("gui-menubar")).toHaveCount(0);
  await expect(page.getByTestId("gui-sidebar")).toHaveCount(0);
  await expect(page.getByTestId("mode-terminal")).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  await expect(page.locator("html")).toHaveAttribute("data-mode", "terminal");
  await expect(page.getByTestId("gui-menubar")).toHaveCount(0);
  // And back: GUI is stored explicitly, so it survives a reload too.
  await page.getByTestId("mode-gui").click();
  await expect(page.getByTestId("gui-menubar")).toBeVisible();
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  await expect(page.getByTestId("gui-menubar")).toBeVisible();
});

test("Alt+G toggles the mode, and SETTINGS MODE sets it from the command line", async ({ page }) => {
  await setupGui(page);
  await page.keyboard.press("Alt+g");
  await expect(page.locator("html")).toHaveAttribute("data-mode", "terminal");
  await page.keyboard.press("Alt+g");
  await expect(page.locator("html")).toHaveAttribute("data-mode", "gui");
  await page.keyboard.press("Control+k");
  await page.keyboard.type("SETTINGS MODE TERMINAL");
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("data-mode", "terminal");
});

test("a panel keeps its content when the mode is switched (no remount)", async ({ page }) => {
  await setupGui(page);
  await page.locator("#cmdline").fill("AAPL GP");
  await page.locator("#cmdline").press("Enter");
  await expect(header(page)).toContainText("GP");
  await page.getByTestId("mode-terminal").click();
  await expect(page.getByTestId("gui-menubar")).toHaveCount(0);
  await expect(header(page)).toContainText("GP");
});

test("default openApp is the terminal shell", async ({ page }) => {
  await page.routeWebSocket(/\/ws$/, () => {});
  await openApp(page);
  await expect(page.locator("html")).toHaveAttribute("data-mode", "terminal");
  await expect(page.getByTestId("gui-menubar")).toHaveCount(0);
  await expect(page.locator(".app-body")).toHaveCSS("display", "contents");
});
