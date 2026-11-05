// Retakes the README screenshots in docs/screenshots/ against a running OpenTerm with LIVE data.
//
//   1. Build the frontend (cd frontend; npm run build).
//   2. Start a throwaway server on its own port and database, so your saved layouts are not touched:
//        OPENTERM_PORT=8011 OPENTERM_STATIC_DIR=<repo>/frontend/dist OPENTERM_DB_PATH=<temp>/shots.db
//        OPENTERM_KEYRING=memory SEC_USER_AGENT="OpenTerm README screenshots" uv run --no-dev python -m openterm   (from backend/)
//   3. node scripts/screenshots.mjs [name ...]      (no names = all; BASE=http://127.0.0.1:8011 by default)
//
// Needs Playwright's Chromium (`.\scripts\setup.ps1 -Dev` installs it). Every shot uses a fresh browser context, because
// panels are saved to the server and would otherwise pile up from shot to shot.
// Why the page is small: GitHub shows a README picture about 880 px wide whatever its size, so a 1440 px page was shrunk to
// 60% and the 12 px text became unreadable. The page is VIEW_W x VIEW_H CSS pixels (close to the display width, so the text
// shows at about its real size) at 2x pixel density (so it stays sharp when the picture is viewed full size).
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const BASE = process.env.BASE ?? "http://127.0.0.1:8011";
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../docs/screenshots");
const VIEW_W = 960;
const VIEW_H = 600;
const WAIT = Number(process.env.SHOT_WAIT ?? 7000); // ms for live data to arrive before the picture is taken

/** Types a command in the command line. Shift+Enter opens it in a new panel next to the others. */
async function cmd(page, text, { newPanel = false, wait = 1500 } = {}) {
  const input = page.locator(".cmd input").first();
  await input.click();
  await input.fill(text);
  await page.keyboard.press(newPanel ? "Shift+Enter" : "Enter");
  await page.waitForTimeout(wait);
}

/** Closes panels from the last one back until only `n` are left (the GUI starter layout opens three). */
async function keepOnly(page, n) {
  while ((await page.locator("[data-panel]").count()) > n) {
    // Focus the last panel by clicking its title bar, then close it with Alt+W (the web binding; Ctrl+W is the browser's).
    await page.locator("[data-panel]").last().locator(".ph").click();
    await page.keyboard.press("Alt+w");
    await page.waitForTimeout(300);
  }
}

/** Every shot: [file name without .png, mode, async (page) => void that sets the screen up]. */
const SHOTS = [
  // Main picture: GUI mode, the ready-made starter screen (watchlist, chart, news), tiles side by side.
  // The sidebar is hidden so the panels get the width (the category menus then run along the top instead).
  ["workspace", "gui", async (page) => {
    await page.getByTestId("sidebar-toggle").click();
  }],
  // Sidebar open: one panel (DES) next to the list of every function, grouped by topic.
  ["gui-sidebar", "gui", async (page) => {
    await cmd(page, "AAPL DES", { wait: 4000 });
  }],
  ["gui-search", "gui", async (page) => {
    // The GUI has one text box (the command line); typing shows its suggestion list.
    // Menus instead of the sidebar, and the quote panel closed (its rows can read STALE when the stream is quiet), so the picture is the text box.
    await page.getByTestId("sidebar-toggle").click();
    await page.locator('[data-panel="1"] .ph').click();
    await page.keyboard.press("Alt+w");
    await page.waitForTimeout(400);
    const input = page.locator(".cmd input").first();
    await input.click();
    await input.fill("apple stock price past 5 years");
    await page.waitForTimeout(1500);
  }],
  ["gui-glossary", "gui", async (page) => {
    await cmd(page, "AAPL DES", { wait: 4000 });
    await page.locator("[data-term]").first().hover();
    await page.waitForTimeout(800);
  }],
  ["gui-error-next-step", "gui", async (page) => {
    await cmd(page, "ZZZZQ GP", { wait: 3000 });
  }],
  ["chart", "gui", async (page) => {
    await page.getByTestId("sidebar-toggle").click();
    await keepOnly(page, 1); // one big chart instead of three small panels
    await cmd(page, "NVDA GP 1Y SMA20 SMA50 RSI", { wait: 3000 });
  }],
  ["backtest", "terminal", async (page) => {
    await cmd(page, "BT AAPL SMA20>SMA50 1D 5Y", { wait: 6000 });
  }],
  ["fundamentals", "gui", async (page) => {
    await page.getByTestId("sidebar-toggle").click();
    await keepOnly(page, 1);
    await cmd(page, "AAPL DES", { wait: 3000 });
    // HDS (top holders) comes from Yahoo and needs no key; FA needs SEC_USER_AGENT with a real contact address.
    await cmd(page, "AAPL HDS", { newPanel: true, wait: 5000 });
  }],
  ["macro", "terminal", async (page) => {
    await cmd(page, "RATES", { wait: 3000 });
    await cmd(page, "FRED CPIAUCSL", { newPanel: true, wait: 5000 });
  }],
  ["bt-editor", "terminal", async (page) => {
    await cmd(page, "BT EDIT demo", { wait: 2500 });
    // The template picker has the focus after Esc: pick the second row (RSI mean reversion) and load it.
    await page.keyboard.press("Escape");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(2500);
  }],
];

const wanted = process.argv.slice(2);
const browser = await chromium.launch();
for (const [name, mode, setup] of SHOTS) {
  if (wanted.length && !wanted.includes(name)) continue;
  const ctx = await browser.newContext({ viewport: { width: VIEW_W, height: VIEW_H }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  // Seed the same browser storage the e2e tests use: GUI or Terminal mode, welcome card already seen, panels as tiles.
  await page.addInitScript((m) => {
    // GUI mode leaves "welcomed" unset on purpose: a first-time GUI user is what gets the starter layout (watchlist, chart, news).
    if (m !== "gui") localStorage.setItem("openterm.welcomed", "1");
    localStorage.setItem("openterm.guiTabs", "0");
    localStorage.setItem("openterm.settings", JSON.stringify({ settings: m === "gui" ? { mode: "gui" } : {}, updatedAt: 0, dirty: false }));
  }, mode);
  await page.goto(BASE);
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  await page.waitForTimeout(1200);
  if (mode === "gui") {
    // Close the welcome card (Esc) and the blue "Switch to Terminal mode" banner so the panels are the picture.
    await page.keyboard.press("Escape");
    const banner = page.locator('button:has-text("×")').first();
    if (await banner.count()) await banner.click();
    await page.waitForTimeout(500);
  }
  await setup(page);
  await page.waitForTimeout(WAIT);
  await page.screenshot({ path: path.join(OUT, name + ".png") });
  console.log("saved", name);
  await ctx.close();
}
await browser.close();
