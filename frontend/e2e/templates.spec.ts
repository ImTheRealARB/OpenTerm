import { expect, test } from "@playwright/test";
import { openApp } from "./app";
import { bars, env, quote } from "./p19util";

// Mocked routes only (no network).
async function mock(page: import("@playwright/test").Page) {
  await page.route("**/api/**", (r) => r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "test: not mocked" } }));
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
}

const fns = (page: import("@playwright/test").Page) => page.locator("[data-panel] .ph").allInnerTexts();

test("GUI: one click on Settings > Template: Day trader replaces the starter layout (no question asked)", async ({ page }) => {
  await mock(page);
  await openApp(page, { mode: "gui", welcome: true }); // a first run gets the starter layout
  await expect(page.getByTestId("welcome-card")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("welcome-card")).toHaveCount(0);
  await expect(page.locator("[data-panel]")).toHaveCount(3); // starter layout
  await page.getByTestId("sidebar-toggle").click(); // the horizontal menus replace the sidebar
  await page.locator('.gm-cat[data-cat="Settings"]').click();
  await page.locator('.gm-sub[data-group="Look and layout"]').hover(); // the templates live in this group's flyout
  await page.locator('.gm-item[data-template="DAY"]').click();
  await expect(page.locator("[data-panel]")).toHaveCount(4);
  await expect(page.locator('[data-panel="1"] .ph')).toContainText("GP");
  await expect(page.locator('[data-panel="2"] .ph')).toContainText("Q");
  await expect(page.locator('[data-panel="3"] .ph')).toContainText("MOV");
  await expect(page.locator('[data-panel="4"] .ph')).toContainText("N");
  await expect(page.getByTestId("tmpl-confirm")).toHaveCount(0);
});

test("Terminal: TMPL MACRO applies the Macro template", async ({ page }) => {
  await mock(page);
  await openApp(page);
  await page.keyboard.press("Control+k");
  await page.keyboard.type("TMPL MACRO");
  await page.keyboard.press("Enter");
  await expect(page.locator("[data-panel]")).toHaveCount(5);
  const heads = (await fns(page)).join(" | ");
  for (const c of ["ECO", "MACRO", "WEI", "FX", "CMDTY"]) expect(heads).toContain(c);
});

test("a customised workspace asks once before it is replaced; Esc keeps it, Enter replaces it", async ({ page }) => {
  await mock(page);
  await openApp(page);
  const cmd = async (t: string) => {
    await page.keyboard.press("Control+k");
    await page.keyboard.type(t);
    await page.keyboard.press("Enter");
  };
  await cmd("TMPL INDIA"); // lone HELP panel: replaced without asking
  await expect(page.locator("[data-panel]")).toHaveCount(4);
  await cmd("TMPL DAY"); // now customised: asks
  const ask = page.getByTestId("tmpl-confirm");
  await expect(ask).toContainText("REPLACE CURRENT PANELS");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await expect(ask).toHaveCount(0);
  await expect(page.locator("[data-panel]")).toHaveCount(4);
  await cmd("TMPL DAY");
  await expect(ask).toBeVisible();
  await page.keyboard.press("Escape"); // leave the command line, then confirm with Enter on the panel
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-panel="1"] .ph')).toContainText("GP");
  await expect(page.locator('[data-panel="3"] .ph')).toContainText("MOV");
});

test("TMPL with no name lists the four templates; an unknown name says so", async ({ page }) => {
  await mock(page);
  await openApp(page);
  await page.keyboard.press("Control+k");
  await page.keyboard.type("TMPL NOPE");
  await page.keyboard.press("Enter");
  const p = page.locator('[data-panel="1"]');
  await expect(p).toContainText("NO TEMPLATE NOPE");
  for (const t of ["LONGTERM", "DAY", "MACRO", "INDIA"]) await expect(p).toContainText(t);
});
