import type { Page } from "@playwright/test";

/**
 * Opens the app and waits until it is ready. Register page.route / routeWebSocket mocks first.
 * Every test gets a fresh browser context, so localStorage starts empty: no clear-and-reload needed.
 *
 * Shell mode: a brand-new user (empty localStorage, nothing on the server) starts in GUI mode, but the whole e2e suite
 * was written for the terminal shell. So by default this seeds the settings mirror (`openterm.settings`, see
 * settings/runtime.ts) with `{}`: "saved settings without a mode" means terminal. Pass `{ mode: "gui" }` to get the
 * GUI shell instead (the seed then stores `mode: "gui"`).
 *
 * The seed runs before every page load of this page (including `page.reload()`), but only when nothing is stored
 * yet, so a mode switched during a test survives a reload, and a test that clears localStorage on purpose gets a
 * fresh seed on its next load.
 *
 * `welcome: true` leaves the first-run welcome card unseeded, so a GUI-mode test sees it once (default: already seen).
 */
export async function openApp(page: Page, opts: { mode?: "terminal" | "gui"; welcome?: boolean; tabs?: boolean; statusBar?: boolean } = {}) {
  const settings = opts.mode === "gui" ? { mode: "gui" } : {};
  const seedWelcomed = !opts.welcome;
  // GUI mode shows panels as tabs by default; older tests expect tiles, so they start with tabs off unless `tabs: true`.
  const seedTabs = opts.tabs ? "1" : "0";
  // GUI mode hides the bottom status bar by default (the mode switch lives in it), so tests start with it ON unless `statusBar: false`.
  const seedStatus = opts.statusBar === false ? "0" : "1";
  await page.addInitScript(({ seed, seedWelcomed, seedTabs, seedStatus }) => {
    try {
      if (localStorage.getItem("openterm.statusBarShown") === null) localStorage.setItem("openterm.statusBarShown", seedStatus);
      // The first-run welcome card (GUI mode, localStorage `openterm.welcomed`) would cover the workspace in every GUI test,
      // so it counts as already seen unless the test asks for it with `welcome: true`.
      if (seedWelcomed && localStorage.getItem("openterm.welcomed") === null) localStorage.setItem("openterm.welcomed", "1");
      if (localStorage.getItem("openterm.guiTabs") === null) localStorage.setItem("openterm.guiTabs", seedTabs);
      if (localStorage.getItem("openterm.settings") === null) {
        // updatedAt 0 + dirty false: this is not an edit, so settings sync neither pushes it nor treats it as newer than the server's copy.
        localStorage.setItem("openterm.settings", JSON.stringify({ settings: seed, updatedAt: 0, dirty: false }));
      }
    } catch {
      /* storage unavailable: the app then starts in its default shell */
    }
  }, { seed: settings, seedWelcomed, seedTabs, seedStatus });
  await page.goto("/");
  await page.waitForFunction(() => window.__openterm_perf?.ready);
}
