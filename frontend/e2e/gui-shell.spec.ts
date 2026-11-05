import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";
import { bars, env, quote } from "./p19util";

/**
 * GUI mode, step A: menu bar, sidebar, command line, status-bar mode switch. Mocked routes only (no network).
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
  await page.getByTestId("sidebar-toggle").click(); // the horizontal menus replace the sidebar
  // The status bar and font rows live in Settings > Look and layout (the group's flyout opens on hover).
  const settingsMenu = async () => {
    await page.locator('.gm-cat[data-cat="Settings"]').click();
    await page.locator('.gm-sub[data-group="Look and layout"]').hover();
  };
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

test("a fresh GUI shows the sidebar (not the category menus), and no page errors", async ({ page }) => {
  const { errors } = await setupGui(page);
  await expect(page.locator("html")).toHaveAttribute("data-mode", "gui");
  const bar = page.getByTestId("gui-menubar");
  await expect(bar).toBeVisible(); // the strip stays: it holds the Sidebar and Tabs/Tiles buttons
  await expect(bar.locator(".gm-cat")).toHaveCount(0); // the sidebar already lists every category
  await expect(page.getByTestId("gui-sidebar")).toBeVisible();
  await expect(page.getByTestId("gui-sidebar").locator(".gs-head")).toHaveCount(7);
  // The command line, workspace and status bar are still there.
  await expect(page.locator(".cmd input")).toBeVisible();
  await expect(page.locator('[data-panel="1"]')).toBeVisible();
  await expect(page.getByTestId("mode-gui")).toHaveAttribute("aria-pressed", "true");
  expect(errors).toEqual([]);
});

test("the Sidebar button swaps the sidebar for the category menus and back (one or the other, never both)", async ({ page }) => {
  await setupGui(page);
  const bar = page.getByTestId("gui-menubar");
  await page.getByTestId("sidebar-toggle").click();
  await expect(page.getByTestId("gui-sidebar")).toHaveCount(0);
  await expect(bar.locator(".gm-cat")).toHaveText(["Markets", "Charts", "News", "Research", "Portfolio", "Backtest", "Settings"]);
  await page.getByTestId("sidebar-toggle").click();
  await expect(page.getByTestId("gui-sidebar")).toBeVisible();
  await expect(bar.locator(".gm-cat")).toHaveCount(0);
});

test("with the status bar off there is no empty strip under the workspace", async ({ page }) => {
  await setupGui(page, { statusBar: false });
  await expect(page.locator("footer.status")).toHaveCount(0);
  // The workspace's bottom edge is the bottom of the window (nothing reserved for the hidden footer).
  const gap = await page.evaluate(() => window.innerHeight - document.querySelector(".ws")!.getBoundingClientRect().bottom);
  expect(gap).toBeLessThanOrEqual(1);
});

test("command line: GP + Enter opens the chart in the focused panel", async ({ page }) => {
  await setupGui(page);
  // GP needs a security: a bare ticker on the command line loads one first.
  await page.locator("#cmdline").fill("AAPL");
  await page.locator("#cmdline").press("Enter");
  await expect(header(page)).toContainText("AAPL");
  await page.locator("#cmdline").fill("GP");
  await page.locator("#cmdline").press("Enter");
  await expect(header(page)).toContainText("GP");
  await expect(header(page)).toContainText("AAPL");
});

test("a bare ticker on the command line keeps the panel's function in GUI: GP of AAPL becomes GP of MSFT", async ({ page }) => {
  await setupGui(page);
  await page.locator("#cmdline").fill("AAPL GP");
  await page.locator("#cmdline").press("Enter");
  await expect(header(page)).toContainText("GP");
  await page.locator("#cmdline").fill("MSFT");
  await page.locator("#cmdline").press("Enter");
  await expect(header(page)).toContainText("MSFT");
  await expect(header(page)).toContainText("GP");
});

test("the GO button runs the typed text like Enter does (GUI only) and keeps the focus in the command line", async ({ page }) => {
  await setupGui(page);
  await page.locator("#cmdline").fill("AAPL GP");
  await page.locator("button.cmd-go").click();
  await expect(header(page)).toContainText("GP");
  await expect(header(page)).toContainText("AAPL");
  await expect(page.locator("#cmdline")).toHaveValue(""); // the line clears after a run, as with Enter
  await expect(page.locator("#cmdline")).toBeFocused();
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
  // A long category (Markets) shows plain-word groups; a group opens a flyout beside the sidebar with its functions.
  await side.locator(".gs-head", { hasText: "Markets" }).click();
  const crypto = side.locator('.gs-sub[data-group="Crypto"]');
  await crypto.click();
  const fly = page.getByTestId("gs-flyout");
  await expect(fly.locator('.gs-item[data-code="CRYP"]')).toBeVisible();
  // Keyboard: ArrowLeft goes back to the group row, ArrowRight opens the flyout again with its first row focused.
  await fly.locator(".gs-item").first().focus();
  await page.keyboard.press("ArrowLeft");
  await expect(fly).toHaveCount(0);
  await expect(crypto).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(fly.locator(".gs-item").first()).toBeFocused();
  await fly.locator('.gs-item[data-code="CRYP"]').click();
  await expect(fly).toHaveCount(0);
  await expect(header(page)).toContainText("CRYP");
  // GP without any security: the same error the command line gives.
  await page.locator("#cmdline").fill("GP");
  await page.locator("#cmdline").press("Enter");
  await expect(page.locator(".msg")).toContainText("GP NEEDS A SECURITY");
});

test("menu bar: a long category opens plain-word groups, a group opens a flyout, picking a function runs it; keys step in and out", async ({ page }) => {
  await setupGui(page);
  await page.getByTestId("sidebar-toggle").click(); // the horizontal menus replace the sidebar
  const bar = page.getByTestId("gui-menubar");
  const fly = page.getByTestId("gm-flyout");
  await bar.locator(".gm-cat", { hasText: "Settings" }).click();
  const drop = bar.locator(".gm-drop");
  await expect(drop).toBeVisible();
  await drop.locator('.gm-sub[data-group="Look and layout"]').hover();
  await expect(fly.locator(".gm-item", { hasText: "Switch to Terminal mode" })).toBeVisible();
  await drop.locator('.gm-sub[data-group="Help"]').hover(); // hovering another group switches the flyout
  await fly.locator('.gm-item:has-text("Keyboard shortcuts")').click();
  await expect(drop).toHaveCount(0);
  await expect(header(page)).toContainText("SHORTCUTS");
  // A short category lists its functions directly: no second level.
  await bar.locator(".gm-cat", { hasText: "News" }).click();
  await expect(drop.locator(".gm-sub")).toHaveCount(0);
  await expect(drop.locator('.gm-item:has-text("Daily brief")')).toBeVisible();
  await bar.locator(".gm-cat", { hasText: "News" }).click();
  // Keyboard: Enter opens Markets on its first group; ArrowRight opens that group's flyout on its first function;
  // ArrowLeft goes back to the group; Esc closes the menu and returns to the command line.
  await bar.locator(".gm-cat", { hasText: "Markets" }).focus();
  await page.keyboard.press("Enter");
  const first = drop.locator(".gm-sub").first();
  await expect(first).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(fly.locator(".gm-item").first()).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(fly).toHaveCount(0);
  await expect(first).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(drop).toHaveCount(0);
  await expect(page.locator(".cmd input")).toBeFocused();
});

test("a flyout near the right edge opens to the left so it stays on screen", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 700 });
  await setupGui(page);
  await page.getByTestId("sidebar-toggle").click(); // the horizontal menus replace the sidebar
  const bar = page.getByTestId("gui-menubar");
  await bar.locator(".gm-cat", { hasText: "Settings" }).click();
  await bar.locator('.gm-sub[data-group="Look and layout"]').hover();
  const box = await page.getByTestId("gm-flyout").boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(1000);
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
