import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

const cmd = async (page: Page, text: string, key = "Enter") => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  await page.keyboard.press(key);
};
const panel = (page: Page, id: number) => page.locator(`[data-panel="${id}"]`);
const panels = (page: Page) => page.locator("[data-panel]");
const msg = (page: Page) => page.locator(".msg");

/** In-memory stand-in for the SQLite-backed endpoints (the backend side is covered by pytest). */
async function fakeBackend(page: Page, storedHistory: string[] = []) {
  const layouts = new Map<string, { state: unknown; updated_at: number }>();
  const calls: string[] = [];
  const posted: string[] = [];
  await page.route("**/api/layouts**", async (r) => {
    const req = r.request();
    const name = decodeURIComponent(new URL(req.url()).pathname.split("/api/layouts")[1].replace(/^\//, "")).toUpperCase();
    calls.push(`${req.method()} ${name}`);
    if (!name) {
      const list = [...layouts].map(([n, v]) => ({
        name: n,
        panels: Object.keys((v.state as { panels: object }).panels).length,
        updated_at: v.updated_at,
      }));
      return r.fulfill({ json: { layouts: list.sort((a, b) => a.name.localeCompare(b.name)) } });
    }
    if (req.method() === "PUT") {
      layouts.set(name, { state: req.postDataJSON().state, updated_at: Date.now() / 1000 });
      return r.fulfill({ json: { name, updated_at: Date.now() / 1000 } });
    }
    const hit = layouts.get(name);
    if (!hit) return r.fulfill({ status: 404, json: { error: `NO LAYOUT ${name}`, kind: "not_found" } });
    if (req.method() === "DELETE") {
      layouts.delete(name);
      return r.fulfill({ json: { deleted: name } });
    }
    return r.fulfill({ json: { name, ...hit } });
  });
  await page.route("**/api/cmdhistory", async (r) => {
    if (r.request().method() === "POST") {
      posted.push(...r.request().postDataJSON().cmds);
      return r.fulfill({ json: { added: 1 } });
    }
    return r.fulfill({ json: { items: storedHistory } });
  });
  return { layouts, calls, posted };
}

test("LAYOUT SAVE, LOAD by Ctrl+O, Ctrl+S re-save, survives a reload", async ({ page }) => {
  const be = await fakeBackend(page);
  await openApp(page);
  await expect(page.locator(".status")).toContainText("LAYOUT NONE");

  await cmd(page, "AAPL DES");
  await page.keyboard.press("Control+\\");
  await cmd(page, "2: Q AAPL MSFT");
  await cmd(page, "LAYOUT SAVE desk");
  await expect(msg(page)).toHaveText("LAYOUT DESK SAVED (2 PANELS)");
  await expect(page.locator(".status")).toContainText("LAYOUT DESK");
  const saved = be.layouts.get("DESK")!.state as { panels: Record<string, { views: { fn?: string }[] }> };
  expect(saved.panels["2"].views).toEqual([{ fn: "Q", security: { symbol: "AAPL" }, args: ["AAPL", "MSFT"] }]); // sticky security

  // Change the workspace, then bring the layout back from the keyboard.
  await page.keyboard.press("Alt+w");
  await expect(panels(page)).toHaveCount(1);
  await page.keyboard.press("Control+o");
  await expect(page.locator("#cmdline")).toBeFocused();
  await expect(page.locator("#cmdline")).toHaveValue("LAYOUT LOAD ");
  await expect(page.locator(".ac")).toContainText("DESK");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(msg(page)).toHaveText("LAYOUT DESK LOADED");
  await expect(panels(page)).toHaveCount(2);
  await expect(panel(page, 2).locator(".ph")).toContainText("Q");
  await expect(panel(page, 1).locator(".ph")).toContainText("AAPL | DES");

  // Ctrl+S re-saves the layout in use without asking for a name.
  await page.keyboard.press("Escape");
  const puts = be.calls.filter((c) => c === "PUT DESK").length;
  await page.keyboard.press("Control+s");
  await expect(msg(page)).toHaveText("LAYOUT DESK SAVED (2 PANELS)");
  expect(be.calls.filter((c) => c === "PUT DESK").length).toBe(puts + 1);

  // Fresh session (the workspace lives in localStorage): loading by name rebuilds the same panels.
  await page.evaluate(() => localStorage.clear());
  await openApp(page);
  await expect(panels(page)).toHaveCount(1);
  await cmd(page, "MONITOR desk");
  await expect(panels(page)).toHaveCount(2);
  await expect(panel(page, 2).locator(".ph")).toContainText("Q");
});

test("Ctrl+S without a layout name asks for one; bad names and missing layouts are errors", async ({ page }) => {
  await fakeBackend(page);
  await openApp(page);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+s");
  await expect(page.locator("#cmdline")).toHaveValue("LAYOUT SAVE ");
  await page.keyboard.press("Escape");
  await cmd(page, "LAYOUT SAVE my/desk");
  await expect(page.locator(".msg.err")).toHaveText("LAYOUT NAME: 1-32 OF A-Z 0-9 _ . -");
  await cmd(page, "LAYOUT LOAD nothere");
  await expect(page.locator(".msg.err")).toHaveText("NO LAYOUT NOTHERE");
  await cmd(page, "LAYOUT SAVE");
  await expect(page.locator(".msg.err")).toContainText("NEEDS A NAME");
});

test("LAYOUT panel: list, keyboard load, delete needs a second press", async ({ page }) => {
  const be = await fakeBackend(page);
  await openApp(page);
  await cmd(page, "LAYOUT SAVE ALPHA");
  await expect(msg(page)).toContainText("SAVED");
  await page.keyboard.press("Control+\\");
  await cmd(page, "LAYOUT SAVE BETA");
  await expect(msg(page)).toContainText("SAVED");

  await cmd(page, "LAYOUT");
  const p = panel(page, 2);
  await expect(p).toContainText("ALPHA");
  await expect(p.locator("tr.on")).toContainText("ALPHA");
  await expect(p.locator("tr", { hasText: "BETA" })).toContainText("CURRENT");
  await page.keyboard.press("Escape"); // leave the command line; keys now go to the panel
  await page.keyboard.press("j");
  await expect(p.locator("tr.on")).toContainText("BETA");
  await page.keyboard.press("Delete");
  await expect(p).toContainText("DELETE? PRESS DEL AGAIN");
  await page.keyboard.press("Escape");
  await expect(p).not.toContainText("DELETE?");
  expect(be.layouts.has("BETA")).toBe(true);
  await page.keyboard.press("Delete");
  await page.keyboard.press("Delete");
  await expect(msg(page)).toHaveText("LAYOUT BETA DELETED");
  await expect(p.locator("tbody tr")).toHaveCount(1);
  expect(be.layouts.has("BETA")).toBe(false);
  await expect(page.locator(".status")).toContainText("LAYOUT NONE");

  await page.keyboard.press("Enter"); // load ALPHA: one panel
  await expect(msg(page)).toHaveText("LAYOUT ALPHA LOADED");
  await expect(panels(page)).toHaveCount(1);
});

test("command history comes from and goes to the SQLite API", async ({ page }) => {
  const be = await fakeBackend(page, ["AAPL DES", "Q"]);
  await openApp(page);
  await page.keyboard.press("Control+k");
  await page.keyboard.press("ArrowUp");
  await expect(page.locator("#cmdline")).toHaveValue("Q");
  await page.keyboard.press("ArrowUp");
  await expect(page.locator("#cmdline")).toHaveValue("AAPL DES");
  await page.keyboard.press("Control+a");
  await page.keyboard.type("HELP");
  await page.keyboard.press("Enter");
  await expect.poll(() => be.posted).toEqual(["HELP"]);
  expect(await page.evaluate(() => localStorage.getItem("openterm.cmdHistory"))).toBeNull();
});

test("Ctrl+Shift+Arrows resize the focused panel without a mouse", async ({ page }) => {
  await fakeBackend(page);
  await openApp(page);
  await page.keyboard.press("Control+\\");
  await page.keyboard.press("Control+-"); // panel 3 under panel 2
  await expect(panels(page)).toHaveCount(3);
  const w = async (id: number) => (await panel(page, id).boundingBox())!.width;
  const h = async (id: number) => (await panel(page, id).boundingBox())!.height;
  const [w1, h3] = [await w(1), await h(3)];

  // Panel 3 is focused: Left moves the vertical divider left (panel 1 narrower, 3 wider).
  await page.keyboard.press("Control+Shift+ArrowLeft");
  expect(await w(1)).toBeLessThan(w1 - 20);
  // Down moves the horizontal divider between 2 and 3 down: panel 3 gets shorter.
  await page.keyboard.press("Control+Shift+ArrowDown");
  expect(await h(3)).toBeLessThan(h3 - 10);
  // Ratios clamp at 10-90 %: many presses never collapse a panel.
  for (let i = 0; i < 30; i++) await page.keyboard.press("Control+Shift+ArrowRight");
  expect(await w(3)).toBeGreaterThan(50);
});

test("a saved layout naming a function that no longer exists loads it as an empty panel, not a crash", async ({ page }) => {
  const be = await fakeBackend(page);
  // UNLK used to be a registry stub and is gone; a layout saved back then still names it. Panel 2 is a normal function.
  be.layouts.set("OLD", {
    updated_at: 1,
    state: {
      layout: { t: "split", dir: "v", ratio: 0.5, a: { t: "leaf", id: 1 }, b: { t: "leaf", id: 2 } },
      panels: {
        1: { id: 1, views: [{ fn: "UNLK", args: [] }], pos: 0 },
        2: { id: 2, views: [{ fn: "Q", args: ["AAPL"] }], pos: 0 },
      },
      focus: 1,
    },
  });
  await openApp(page);
  await cmd(page, "LAYOUT OLD");
  await expect(msg(page)).toHaveText("LAYOUT OLD LOADED");
  await expect(panels(page)).toHaveCount(2);
  await expect(panel(page, 1)).toContainText("EMPTY PANEL"); // the unknown function was dropped, the panel stays
  await expect(panel(page, 2).locator(".ph")).toContainText("Q");
});
