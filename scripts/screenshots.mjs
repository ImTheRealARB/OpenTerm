// Retakes the README screenshots in docs/screenshots/ against a running OpenTerm with LIVE data.
//
//   1. Build the frontend (cd frontend; npm run build).
//   2. Start a throwaway server on its own port and database, so your saved layouts are not touched:
//        OPENTERM_PORT=8011 OPENTERM_STATIC_DIR=<repo>/frontend/dist OPENTERM_DB_PATH=<temp>/shots.db
//        OPENTERM_KEYRING=memory SEC_USER_AGENT="OpenTerm README screenshots" uv run --no-dev python -m openterm   (from backend/)
//   3. node scripts/screenshots.mjs [name ...]      (no names = all; BASE=http://127.0.0.1:8011 by default)
//
// Needs Playwright's Chromium (`.\scripts\setup.ps1 -Dev` installs it). Every shot uses a fresh browser context, because
// panels are saved to the server and would otherwise pile up from shot to shot. The page is 1440x810 CSS pixels at 2x
// pixel density: the text looks larger in the README than the old 1600x900 shots (the old ones were 1600x900 CSS pixels), and stays sharp.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const BASE = process.env.BASE ?? "http://127.0.0.1:8011";
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../docs/screenshots");
const WAIT = Number(process.env.SHOT_WAIT ?? 7000); // ms for live data to arrive before the picture is taken

/** Types a command in the command line. Shift+Enter opens it in a new panel next to the others. */
async function cmd(page, text, { newPanel = false, wait = 1500 } = {}) {
  const input = page.locator(".cmd input").first();
  await input.click();
  await input.fill(text);
  await page.keyboard.press(newPanel ? "Shift+Enter" : "Enter");
  await page.waitForTimeout(wait);
}

/** Every shot: [file name without .png, mode, async (page) => void that sets the screen up]. */
const SHOTS = [
  // Main picture: GUI mode, the ready-made starter screen (watchlist, chart, news), tiles side by side.
  // The sidebar is hidden so the panels get the width: with it, the quote grid's price columns are cut off at this page size.
  ["workspace", "gui", async (page) => {
    await page.getByTestId("sidebar-toggle").click();
  }],
  ["gui-search", "gui", async (page) => {
    await page.getByPlaceholder("Company or ticker").fill("apple");
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
  ["chart", "terminal", async (page) => {
    await cmd(page, "NVDA GP 1Y SMA20 SMA50 RSI", { wait: 3000 });
  }],
  ["backtest", "terminal", async (page) => {
    await cmd(page, "BT AAPL SMA20>SMA50 1D 5Y", { wait: 6000 });
  }],
  ["fundamentals", "terminal", async (page) => {
    await cmd(page, "AAPL DES", { wait: 3000 });
    await cmd(page, "AAPL FA", { newPanel: true, wait: 5000 });
  }],
  ["macro", "terminal", async (page) => {
    await cmd(page, "RATES", { wait: 3000 });
    await cmd(page, "ECO 30 MAJOR", { newPanel: true, wait: 5000 });
  }],
  ["bt-editor", "terminal", async (page) => {
    await cmd(page, "BT EDIT demo", { wait: 2500 });
  }],
];

const wanted = process.argv.slice(2);
const browser = await chromium.launch();
for (const [name, mode, setup] of SHOTS) {
  if (wanted.length && !wanted.includes(name)) continue;
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 810 }, deviceScaleFactor: 2 });
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
