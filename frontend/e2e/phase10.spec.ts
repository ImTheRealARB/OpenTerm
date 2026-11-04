import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

/** Phase 10: SETTINGS panel, themes, vim mode, keybinding overrides. /api/settings is mocked; no network. */

interface Doc {
  settings: Record<string, unknown> | null;
  updated_at: number | null;
}

async function setup(page: Page, initial: Doc = { settings: null, updated_at: null }) {
  const server: Doc = { ...initial };
  const puts: Record<string, any>[] = [];
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/settings", (r) => {
    const req = r.request();
    if (req.method() === "PUT") {
      const body = req.postDataJSON();
      puts.push(body.settings);
      server.settings = body.settings;
      server.updated_at = Date.now() / 1000;
      return r.fulfill({ json: { version: 1, settings: server.settings, updated_at: server.updated_at } });
    }
    return r.fulfill({ json: { version: 1, ...server } });
  });
  await openApp(page);
  return { server, puts };
}

const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape"); // leave the command line: letters go to the panel
};
/** Opens SETTINGS and waits until its panel keys are registered (the module loads async): J moves, then G goes back to the top. */
const openSettings = async (page: Page, id = 1) => {
  await run(page, "SETTINGS");
  const row = panel(page, id).locator("tr.on");
  await expect(row).toContainText("THEME");
  await expect(async () => {
    await page.keyboard.press("Escape"); // an early "j" would have started typing in the command line
    await page.keyboard.press("j");
    await expect(row).not.toHaveAttribute("data-row", "theme", { timeout: 250 });
  }).toPass();
  await page.keyboard.press("g");
  await expect(row).toHaveAttribute("data-row", "theme");
};
/** Esc from insert mode. The first Esc only closes the suggestion list when it is open, so retry until NORMAL shows. */
const toNormal = (page: Page) =>
  expect(async () => {
    await page.keyboard.press("Escape");
    await expect(page.locator(".cmd .vim")).toContainText("-- NORMAL --", { timeout: 1000 });
  }).toPass();
const panel = (page: Page, id = 1) => page.locator(`[data-panel="${id}"]`);
const theme = (page: Page) => page.evaluate(() => document.documentElement.getAttribute("data-theme"));
const bg = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

test("SETTINGS: edit a value with the keyboard, it applies at once, is saved on the server and survives a reload", async ({ page }) => {
  const { server, puts } = await setup(page);
  await openSettings(page);
  const p = panel(page);
  await expect(p.locator(".ph")).toContainText("SETTINGS");
  await expect(p.locator("tr.on")).toContainText("THEME");
  await expect(p.locator("tr.on")).toContainText("AMBER ON BLACK");
  expect(await theme(page)).toBeNull();

  await page.keyboard.press("l");
  await expect(p.locator("tr.on")).toContainText("GREEN PHOSPHOR");
  expect(await theme(page)).toBe("green");
  await page.keyboard.press("j");
  await expect(p.locator("tr.on")).toContainText("VIM MODE");
  await page.keyboard.press("l");
  await expect(p.locator("tr.on")).toContainText("ON");

  await expect.poll(() => puts.length).toBeGreaterThan(0); // debounced
  await expect.poll(() => JSON.stringify(puts.at(-1))).toBe('{"theme":"green","vim":true}');
  expect(server.settings).toEqual({ theme: "green", vim: true });

  await page.reload(); // same browser: the localStorage mirror paints the theme
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  expect(await theme(page)).toBe("green");
  await run(page, "SETTINGS");
  await expect(panel(page).locator("tr[data-row='vim']")).toContainText("ON");
});

test("SETTINGS: a fresh browser adopts the copy stored on the server", async ({ page }) => {
  await setup(page, { settings: { theme: "light", chart: { range: "6M", type: "LINE" } }, updated_at: Date.now() / 1000 });
  await expect.poll(() => theme(page)).toBe("light");
  await run(page, "SETTINGS");
  const p = panel(page);
  await expect(p.locator("tr[data-row='chart.range']")).toContainText("6M");
  await expect(p.locator("tr[data-row='chart.type']")).toContainText("LINE");
});

test("SETTINGS: Shift+R twice resets everything", async ({ page }) => {
  const { puts } = await setup(page);
  await run(page, "THEME white");
  // THEME/SETTINGS parsing is a lazy chunk (warmed at idle); a command typed before it arrives runs once it loads.
  await expect.poll(() => theme(page)).toBe("white");
  await openSettings(page);
  await page.keyboard.press("Shift+R");
  await expect(panel(page)).toContainText("RESET ALL SETTINGS? PRESS SHIFT+R AGAIN");
  await page.keyboard.press("Shift+R");
  await expect(panel(page)).toContainText("SETTINGS RESET TO DEFAULTS");
  expect(await theme(page)).toBeNull();
  await expect.poll(() => JSON.stringify(puts.at(-1))).toBe("{}");
});

test("THEME: switches at once, canvas and page colours follow, bad names are refused", async ({ page }) => {
  await setup(page);
  expect(await bg(page)).toBe("rgb(0, 0, 0)");
  await run(page, "THEME light");
  await expect(page.locator(".msg")).toContainText("THEME LIGHT");
  expect(await theme(page)).toBe("light");
  expect(await bg(page)).toBe("rgb(255, 255, 255)");
  await run(page, "THEME green");
  expect(await theme(page)).toBe("green");
  await run(page, "THEME pink");
  await expect(page.locator(".msg.err")).toContainText("THEME: AMBER GREEN WHITE LIGHT");
  expect(await theme(page)).toBe("green");
  await run(page, "THEME amber");
  expect(await theme(page)).toBeNull();
  expect(await bg(page)).toBe("rgb(0, 0, 0)");
});

test("vim mode: off by default, SETTINGS VIM ON adds normal-mode editing in the command line", async ({ page }) => {
  await setup(page);
  await page.keyboard.press("Control+k");
  await expect(page.locator(".cmd .vim")).toHaveCount(0);
  await page.keyboard.type("hello");
  await page.keyboard.press("Escape"); // closes the suggestion list when there is one
  await page.keyboard.press("Escape"); // vim off: leaves the command line
  await expect(page.locator("#cmdline")).not.toBeFocused();

  await run(page, "SETTINGS VIM ON");
  await expect(page.locator(".msg")).toContainText("VIM MODE ON");
  await page.keyboard.press("Control+k");
  await expect(page.locator(".cmd .vim")).toContainText("-- INSERT --");
  await page.locator("#cmdline").fill("GP AAPL");
  await toNormal(page);
  await expect(page.locator("#cmdline")).toBeFocused(); // Esc went to normal mode, not out of the command line
  await page.keyboard.press("0");
  await page.keyboard.press("x");
  await expect(page.locator("#cmdline")).toHaveValue("P AAPL");
  await page.keyboard.press("w");
  await page.keyboard.press("c");
  await page.keyboard.press("w");
  await expect(page.locator(".cmd .vim")).toContainText("-- INSERT --");
  await page.keyboard.type("MSFT");
  await expect(page.locator("#cmdline")).toHaveValue("P MSFT");
  await toNormal(page);
  await page.keyboard.press("d");
  await page.keyboard.press("d");
  await expect(page.locator("#cmdline")).toHaveValue("");
  await page.keyboard.press("Escape"); // normal mode: leaves the command line
  await expect(page.locator("#cmdline")).not.toBeFocused();
});

test("keybinding override: rebind maximize in SETTINGS, the old chord stops working, bad chords are refused", async ({ page }) => {
  const { puts } = await setup(page);
  await page.keyboard.press("Control+\\"); // split: maximize needs two panels to be visible in the status bar
  await openSettings(page, 2);
  const status = page.locator("footer.status");
  await expect(status).toContainText("PANEL 2/2"); // the new panel is focused

  // Default: Ctrl+Shift+F maximizes.
  await page.keyboard.press("Control+Shift+F");
  await expect(status).toContainText("MAX");
  await page.keyboard.press("Control+Shift+F");
  await expect(status).not.toContainText("MAX");

  const p = panel(page, 2);
  const gotoRow = async (row: string) => {
    for (let i = 0; i < 80 && (await p.locator("tr.on").getAttribute("data-row")) !== row; i++) await page.keyboard.press("j");
    await expect(p.locator("tr.on")).toHaveAttribute("data-row", row);
  };
  await gotoRow("maximize");
  await expect(p.locator("tr.on")).toContainText("Ctrl+Shift+F");

  // Refused: taken by another action, and reserved by the browser.
  await page.keyboard.press("Enter");
  await expect(p.locator("tr.on")).toContainText("PRESS A KEY");
  await page.keyboard.press("Control+k");
  await expect(page.locator(".settings [role=status]")).toContainText("IS USED BY focusCommand");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Control+t");
  await expect(page.locator(".settings [role=status]")).toContainText("RESERVED BY THE BROWSER");
  expect(puts).toHaveLength(0);

  // Accepted.
  await page.keyboard.press("Enter");
  await page.keyboard.press("Control+m");
  await expect(p.locator("tr.on")).toContainText("Ctrl+M");
  await expect(p.locator("tr.on")).toContainText("CHANGED");
  await expect.poll(() => JSON.stringify(puts.at(-1))).toBe('{"keys":{"maximize":["Ctrl+M"]}}');

  await page.keyboard.press("Control+Shift+F"); // old chord: nothing
  await expect(status).not.toContainText("MAX");
  await page.keyboard.press("Control+m");
  await expect(status).toContainText("MAX");
  await page.keyboard.press("Control+m");
  await expect(status).not.toContainText("MAX");

  // X restores the default. (Maximizing remounted the panel, so find the row again.)
  await gotoRow("maximize");
  await page.keyboard.press("x");
  await expect(p.locator("tr.on")).toContainText("Ctrl+Shift+F");
  await expect.poll(() => JSON.stringify(puts.at(-1))).toBe("{}");
  await page.keyboard.press("Control+Shift+F");
  await expect(status).toContainText("MAX");
});
