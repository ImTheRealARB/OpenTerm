import { expect, test, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openApp } from "./app";
import { gauge, panel, run } from "./p19util";

/**
 * ONE smoke test for everything Phases 21-32 add (owner's minimal test bar, 2026-11-24): each case types a command, and the
 * panel must show content and the expected text, never UNKNOWN FUNCTION / EMPTY PANEL / an error note. Add one line to CASES
 * per new function or GP mode.
 *
 * Unlike the mocked specs this talks to a REAL backend in fixture mode (recorded answers, no network), started here on its
 * own port so nothing touches :8000: the page's /api calls are forwarded to it. Set SMOKE_SHOTS=<dir> to save a
 * screenshot of every case (for a look by eye).
 */
const PORT = Number(process.env.SMOKE_BE_PORT ?? 8766);
const BE = `http://127.0.0.1:${PORT}`;
const SHOTS = process.env.SMOKE_SHOTS;

interface Case {
  cmd: string;
  /** Text the panel must show once loaded. */
  want: RegExp;
}
const CASES: Case[] = [
  // Phase 21: chart types, candle lengths, patterns
  { cmd: "AAPL GP 1Y RENKO", want: /RENKO BOX .*NON-LINEAR TIME AXIS/ },
  { cmd: "AAPL GP 1Y KAGI", want: /KAGI .*NON-LINEAR TIME AXIS/ },
  { cmd: "AAPL GP 1Y PNF", want: /NON-LINEAR TIME AXIS/ },
  { cmd: "AAPL GP 1Y LINEBREAK", want: /NON-LINEAR TIME AXIS/ },
  { cmd: "AAPL GP 1Y RANGE", want: /NON-LINEAR TIME AXIS/ },
  { cmd: "AAPL GP 1Y VOLCANDLE", want: /AAPL 1Y/ },
  { cmd: "AAPL GP 1Y HIGHLOW", want: /AAPL 1Y/ },
  { cmd: "AAPL GP 1Y STEP", want: /AAPL 1Y/ },
  { cmd: "AAPL GP 1Y COLUMNS", want: /AAPL 1Y/ },
  { cmd: "AAPL GP 1Y 2D", want: /AAPL 1Y 2d/ },
  { cmd: "BTCUSDT GP 1D 1S", want: /BTCUSDT .*1s/ },
  { cmd: "AAPL GP 1Y PAT:GEO", want: /PATTERN RULE, NOT A SIGNAL/ },
  // Phase 22 (synthetic symbols: the fixture backend runs with OPENTERM_SYNTHETIC=1)
  { cmd: "SYN0001/SYN0002 GP 1Y", want: /SYN0001\/SYN0002 1Y/ },
  { cmd: "GP 2*SYN0001-SYN0002 1Y", want: /2\*SYN0001 - SYN0002/ },
  { cmd: "TRA SYN0001 1Y VS SYN0002", want: /SYN0002/ },
  { cmd: "BETA SYN0001 VS SYN0002 1Y", want: /SYN0002/ },
  // Phase 23 (TPO uses the recorded RELIANCE.NS 5-minute day; DOM / LIQH the recorded BTCUSDT book)
  { cmd: "AAPL GP 1Y VP VP:S", want: /VP:S/ },
  { cmd: "AAPL GP 1Y AVWAP AVWAP:W", want: /AVWAP:W/ },
  { cmd: "TPO RELIANCE.NS 1", want: /POC/ },
  { cmd: "DOM BTCUSDT", want: /MID/ },
  { cmd: "LIQH BTCUSDT", want: /SNAPSHOTS/ },
  { cmd: "TAS BTCUSDT", want: /EXACT/ },
  { cmd: "BIGT BTCUSDT USD=1000", want: /EXACT/ },
  { cmd: "FOOT BTCUSDT", want: /EXACT/ },
  // Phase 24
  { cmd: "REC", want: /OFF BY DEFAULT/ },
  { cmd: "AAPL GP 1Y REPLAY", want: /REPLAY .* BAR \d+\/\d+ PAUSED/ },
  // Phase 26
  { cmd: "BT OPT AAPL SMA{10..30:10}>SMA{50..100:50} 1D 10Y", want: /PROB\. OF BACKTEST OVERFITTING/ },
  { cmd: "BT LIVE", want: /PAPER FORWARD TESTS/ },
  { cmd: "BT AAPL SMA20>SMA50 1D 10Y STOP=5 TARGET=10", want: /EXITS: STOP 5% TARGET 10%/ },
  // Phase 27 (LIST: universes, so the fixture backend has bars for every member; a LIST has no index weights)
  { cmd: "SCAN LIST:AAPL,SYN0001,SYN0002 RSI14<101", want: /MATCH OF \d+ CHECKED/ },
  { cmd: "MRR LIST:AAPL,SYN0001,SYN0002 1M", want: /NO INDEX WEIGHTS FOR THIS LIST/ },
  { cmd: "ALRT", want: /INDICATOR ALERTS: ALRT AAPL RSI14<30/ },
  { cmd: "Q AAPL SYN0001 COLS=RSI14<101,PCT_SMA20,REL_VOL", want: /COLS: NEWEST DAILY BAR \(TO / },
  { cmd: "FSRC", want: /29 OF 30 US ETFS LOADED/ },
  { cmd: "FSRC FEE<0.2 AUM>1B CAT=LARGE", want: /8 MATCH/ },
  { cmd: "IMAP CRYPTO", want: /IMAP CRYPTO/ },
  { cmd: "IMAP ETF", want: /TOTAL ASSETS/ },
  { cmd: "IMAP NIFTY", want: /NIFTY50 MEMBERS/ },
];

let backend: ChildProcess | null = null;

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  test.setTimeout(120_000);
  // A server already on the port would be a leftover with an old database: refuse it rather than test against it.
  if (await fetch(`${BE}/api/perf`).then((r) => r.ok, () => false)) throw new Error(`${BE} already answers: stop the leftover backend first`);
  const dir = mkdtempSync(join(tmpdir(), "openterm-smoke-"));
  backend = spawn("uv run python -m openterm", {
    cwd: join(process.cwd(), "..", "backend"),
    shell: true,
    stdio: "ignore",
    env: {
      ...process.env,
      OPENTERM_FIXTURES: "1",
      OPENTERM_SYNTHETIC: "1",
      OPENTERM_PORT: String(PORT),
      OPENTERM_DB_PATH: join(dir, "smoke.db"),
      OPENTERM_KEYRING: "memory",
      OPENTERM_DOTENV_PATH: join(dir, "keys.env"),
    },
  });
  for (let i = 0; i < 120; i++) {
    if (await fetch(`${BE}/api/perf`).then((r) => r.ok, () => false)) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`fixture backend did not start on ${BE}`);
});

test.afterAll(() => {
  if (!backend?.pid) return;
  // shell -> uv -> python: stop the whole tree, or a backend keeps the port for the next run. Synchronous: after a
  // failure the worker exits right after this hook, which would kill an async taskkill before it ran.
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(backend.pid), "/T", "/F"], { stdio: "ignore" });
  else process.kill(-backend.pid, "SIGTERM");
});

async function connect(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  // The live socket is not part of the smoke: answer its pings so the status bar stays quiet.
  await page.routeWebSocket(/\/ws$/, (ws) => ws.onMessage((m) => {
    const msg = JSON.parse(String(m));
    if (msg[0] === "ping") ws.send(JSON.stringify(["pong", msg[1], Date.now()]));
  }));
  await page.route("**/api/**", async (route) => {
    const u = new URL(route.request().url());
    await route.fulfill({ response: await route.fetch({ url: `${BE}${u.pathname}${u.search}` }) });
  });
  await openApp(page);
  return errors;
}

const BAD = /UNKNOWN FUNCTION|EMPTY PANEL|PROVIDER DOWN|NO DATA FOR|BAD (RANGE|INTERVAL)|ONLY AVAILABLE FOR/;

for (const c of CASES) {
  test(`smoke: ${c.cmd}`, async ({ page }) => {
    const errors = await connect(page);
    await run(page, c.cmd);
    const p = panel(page);
    await expect(p).toContainText(c.want, { timeout: 15_000 });
    await expect(p).not.toContainText(BAD);
    if (SHOTS) await page.screenshot({ path: join(SHOTS, `${c.cmd.replace(/[^A-Z0-9]+/gi, "_")}.png`) });
    expect(errors).toEqual([]);
  });
}

test("smoke: drawings by keyboard (tool picker, anchors, text box, object tree) survive a reload", async ({ page }) => {
  const errors = await connect(page);
  // Start from no drawings, whatever an earlier test in this run saved.
  await fetch(`${BE}/api/drawings/AAPL`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ drawings: [] }) });
  await run(page, "AAPL GP 1Y");
  const p = panel(page);
  await expect(p).toContainText("AAPL 1Y", { timeout: 15_000 });
  await expect.poll(() => gauge(page, "chart.rebuilds")).toBeGreaterThan(0);
  // W opens the picker; "a" is the 10th tool (RECTANGLE); the crosshair walks left between the two anchors.
  await page.keyboard.press("w");
  await expect(page.getByTestId("gp-tools")).toBeVisible();
  await page.keyboard.press("a");
  await expect(page.getByTestId("gp-draw-mode")).toContainText("RECTANGLE");
  await page.keyboard.press("Enter");
  for (let i = 0; i < 8; i++) await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("RECTANGLE d1 SELECTED");
  // TEXT (picker key "e") asks for its words once its anchor is in.
  await page.keyboard.press("Escape");
  await page.keyboard.press("w");
  await page.keyboard.press("e");
  await page.keyboard.press("Enter");
  await page.getByTestId("gp-draw-text").fill("earnings gap");
  await page.getByTestId("gp-draw-text").press("Enter");
  await expect(p).toContainText('TEXT "earnings gap" d2 SELECTED');
  await expect.poll(() => gauge(page, "chart.drawSegs")).toBeGreaterThan(1);
  await page.keyboard.press("Escape");
  await page.keyboard.press("o");
  await expect(page.getByTestId("gp-tree-row")).toHaveCount(2);
  if (SHOTS) await page.screenshot({ path: join(SHOTS, "drawings_tree.png") });
  await page.keyboard.press("Escape");
  // Saved 0.4 s after the last change, then read back from the server on reload.
  await page.waitForTimeout(1200);
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  await expect.poll(() => gauge(page, "chart.drawSegs"), { timeout: 15_000 }).toBeGreaterThan(1);
  expect(errors).toEqual([]);
});

test("smoke: LINK A makes a second panel follow a new security", async ({ page }) => {
  const errors = await connect(page);
  await run(page, "AAPL GP 1Y");
  await expect(panel(page, 1)).toContainText(/AAPL 1Y/, { timeout: 15_000 });
  await run(page, "LINK A");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+\\"); // panel 2, focused
  await run(page, "IBM DES");
  await run(page, "LINK A");
  // A new security in panel 2 reaches panel 1 (same group). SYN0002 (synthetic) has bars in the fixture backend; MSFT does
  // not, so panel 1 would end on NO DATA FOR SYMBOL a moment later and make this test flaky.
  await run(page, "SYN0002 DES");
  await expect(panel(page, 1)).toContainText(/SYN0002 1Y/, { timeout: 15_000 });
  await expect(panel(page, 1)).not.toContainText(BAD);
  expect(errors).toEqual([]);
});