import { expect, test, type Page } from "@playwright/test";
import { openApp } from "./app";

// Step C polish: empty / error states of WL and N use the shared PanelNote (data-kind) and name the next action.
// All network answers are mocked; nothing here touches a real provider.

const panel = (page: Page) => page.locator('[data-panel="1"]');
const run = async (page: Page, t: string) => {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(t);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape"); // leave the command line so panel keys work
};

/** A watchlist API with ONE list, named EMPTYLIST, holding no symbols. Anything else is a 404. */
async function mockWatchlists(page: Page, opts: { fail?: boolean } = {}) {
  await page.routeWebSocket(/\/ws$/, (route) => {
    route.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg[0] === "ping") route.send(JSON.stringify(["pong", msg[1], Date.now()]));
    });
  });
  await page.route("**/api/quote?**", (r) => r.fulfill({ json: { results: {} } }));
  await page.route("**/api/watchlists**", (r) => {
    if (opts.fail) return r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "sqlite: locked" } });
    const name = decodeURIComponent(new URL(r.request().url()).pathname.split("/api/watchlists")[1].replace(/^\//, "")).toUpperCase();
    if (!name) return r.fulfill({ json: { watchlists: [{ name: "EMPTYLIST", count: 0, updated_at: Math.floor(Date.now() / 1000) }] } });
    if (name === "EMPTYLIST") return r.fulfill({ json: { name, symbols: [], updated_at: Math.floor(Date.now() / 1000) } });
    return r.fulfill({ status: 404, json: { error: `NO WATCHLIST ${name}`, kind: "not_found" } });
  });
}

test("WL: an empty list shows an empty note whose hint names the add command", async ({ page }) => {
  await mockWatchlists(page);
  await openApp(page);
  await run(page, "WL emptylist");
  const note = panel(page).locator('.pnote[data-kind="empty"]');
  await expect(note).toBeVisible();
  await expect(note).toContainText("EMPTY. A ADDS SYMBOLS");
  await expect(note).toContainText("WL EMPTYLIST ADD AAPL");
});

test("WL: a list that does not exist says how to create it (GUI mode too)", async ({ page }) => {
  await mockWatchlists(page);
  await openApp(page, { mode: "gui" });
  await run(page, "WL nothere");
  const note = panel(page).locator('.pnote[data-kind="empty"]');
  await expect(note).toContainText("NO WATCHLIST NOTHERE");
  await expect(note).toContainText("Add button");
});

test("WL: a failed read shows an error note with the reason, not a blank panel", async ({ page }) => {
  await mockWatchlists(page, { fail: true });
  await openApp(page);
  await run(page, "WL techlist");
  const note = panel(page).locator('.pnote[data-kind="error"]');
  await expect(note).toContainText("UNAVAILABLE");
  await expect(note).toContainText("PROVIDER DOWN");
});

test("N: no headlines shows an empty note with a hint, and a failed fetch shows an error note with the cause", async ({ page }) => {
  await mockWatchlists(page);
  await page.route("**/api/news**", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q");
    if (q === "ZZZ") return r.fulfill({ status: 503, json: { error: "PROVIDER DOWN", kind: "unavailable", detail: "gdelt: rate_limited (429 from upstream)" } });
    const kind = q ? "keyword" : "top";
    return r.fulfill({
      json: {
        data: { kind, query: q, items: [], failed: [] },
        source: "rss",
        as_of: Date.now() / 1000,
        age_s: 0,
        stale: false,
        fallback_from: [],
      },
    });
  });
  await openApp(page);
  await run(page, "N nothing here");
  const empty = panel(page).locator('.pnote[data-kind="empty"]');
  await expect(empty).toContainText("NO HEADLINES");
  await expect(empty).toContainText("NOTHING HERE"); // the keyword query, so the user sees what came back empty

  await run(page, "N zzz");
  const err = panel(page).locator('.pnote[data-kind="error"]');
  await expect(err).toContainText("PROVIDER DOWN");
  await expect(err).toContainText("gdelt: rate_limited");
});
