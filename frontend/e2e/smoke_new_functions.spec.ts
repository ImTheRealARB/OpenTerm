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
  /** Wait longer than the default 15 s (a job that starts a cold worker process: BT OPT: its overfitting step imports scipy cold in the worker, slow under suite load). */
  timeout?: number;
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
  { cmd: "BT OPT AAPL SMA{10..30:10}>SMA{50..100:50} 1D 10Y", want: /PROB\. OF BACKTEST OVERFITTING/, timeout: 90_000 },
  { cmd: "BT LIVE", want: /PAPER FORWARD TESTS/ },
  { cmd: "BT AAPL SMA20>SMA50 1D 10Y STOP=5 TARGET=10", want: /EXITS: STOP 5% TARGET 10%/ },
  // Phase 27 (LIST: universes, so the fixture backend has bars for every member; a LIST has no index weights)
  { cmd: "SCAN LIST:AAPL,SYN0001,SYN0002 RSI14<101", want: /MATCH OF \d+ CHECKED/ },
  { cmd: "MRR LIST:AAPL,SYN0001,SYN0002 1M", want: /NO INDEX WEIGHTS FOR THIS LIST/ },
  // Phase 28 chain recorder (off by default: nothing is recorded in a fresh database)
  { cmd: "OSCAN LIST:AAPL,SYN0001 IVR>50", want: /NOT RECORDED/ },
  { cmd: "AAPL OREC", want: /TURNS IT ON/ },
  { cmd: "AAPL EMOV", want: /AVG ACTUAL MOVE/ },
  { cmd: "AAPL GP 1Y CONE", want: /CONE: MODEL RANGE/ },
  { cmd: "PGRK NOSUCH", want: /NO PORTFOLIO NOSUCH/ },
  { cmd: "AAPL OSA STRAT=BULLCALL,270,290 T=0.3 IV=25 DAYS=14", want: /RISK PROFILE/ },
  { cmd: "AAPL OMON", want: /MAX PAIN/ },
  { cmd: "EURUSD=X OV K=1.1 TYPE=C T=0.5 IV=8 RF=3 RD=4", want: /GARMAN-KOHLHAGEN/ },
  { cmd: "ALRT", want: /INDICATOR ALERTS: ALRT AAPL RSI14<30/ },
  { cmd: "Q AAPL SYN0001 COLS=RSI14<101,PCT_SMA20,REL_VOL", want: /COLS: NEWEST DAILY BAR \(TO / },
  { cmd: "FSRC", want: /29 OF 30 US ETFS LOADED/ },
  { cmd: "FSRC FEE<0.2 AUM>1B CAT=LARGE", want: /8 MATCH/ },
  { cmd: "IMAP CRYPTO", want: /IMAP CRYPTO/ },
  { cmd: "IMAP ETF", want: /TOTAL ASSETS/ },
  { cmd: "IMAP NIFTY", want: /NIFTY50 MEMBERS/ },
  // Phase 29 fundamentals depth (real SEC recordings: AAPL facts, frames for the fixture's filers)
  { cmd: "AAPL GF PE", want: /NO LOOK-AHEAD/ },
  { cmd: "AAPL EM", want: /SEC EPS IS GAAP DILUTED/ },
  { cmd: "AAPL DDIS", want: /PRINCIPAL AT FACE VALUE/ },
  { cmd: "AAPL SCORE", want: /FORMULA SCORE, NOT A RATING/ },
  { cmd: "AAPL REVS", want: /50 x BREADTH/ },
  { cmd: "FRM NetIncomeLoss CY2024", want: /KNOWN DATE = PERIOD END/ },
  { cmd: "IBQ 2024", want: /IQR = 75TH MINUS 25TH/ },
  { cmd: "IBQ 2024 SIC", want: /SIC MAP|SIC CODE = THE INDUSTRY CODE/, timeout: 30_000 },
  { cmd: "EQS ROE>0 MARGIN>0", want: /SEC FIGURES CY20\d\d/, timeout: 30_000 },
  { cmd: "EQS BT MARGIN>0.1 UNIV=LIST:AAPL,MSFT FROM=2023", want: /SURVIVORSHIP BIAS/, timeout: 60_000 },
  // Phase 29: filings (the SEC search is replayed only for the exact recorded query, so these carry the recorded dates)
  { cmd: 'FTS "going concern" FORM=10-K FROM=2024-01-01 TO=2024-12-31', want: /SEC EDGAR FULL-TEXT SEARCH: THE SEC'S OWN INDEX/ },
  { cmd: "MA FROM=2024-10-01 TO=2024-12-31", want: /VALUE: A DOLLAR FIGURE THE FILING TEXT STATES/ },
  { cmd: "AAPL LEGAL", want: /KEY REQUIRED: set COURTLISTENER_API_KEY in APIKEYS/ },
  { cmd: "BIO 1214156 FROM=2023-01-01 TO=2025-12-31", want: /TEXT MATCH FOR "TIMOTHY COOK" IN DEF 14A/ },
  { cmd: "GOOGL RELS", want: /SAME-CIK TICKERS/ },
  { cmd: "AA ESG", want: /EMISSIONS ONLY, NO SCORE/ },
  { cmd: "AA ETS", want: /Alcoa Mosj|VERIFIED t CO2E|EU ETS VERIFIED EMISSIONS/i, timeout: 30_000 },
  // Phase 30: macro, rates and commodities depth
  { cmd: "MMR", want: /P1 \/ P99 = 1ST AND 99TH PERCENTILE/ },
  { cmd: "NOWC", want: /GDPNOW IS A MODEL ESTIMATE/ },
  { cmd: "ECFC", want: /NOT OPENTERM'S/ },
  { cmd: "FOMC", want: /federalreserve\.gov \(CALENDAR, STATEMENTS\)/ },
  { cmd: "WIRP", want: /MARKET-IMPLIED, NOT A FORECAST/ },
  { cmd: "WB", want: /EURO AREA ROW IS THE ECB AAA SPOT CURVE/ },
  { cmd: "CRPR", want: /LAST 3 YEARS OF THE ICE BOFA SERIES/ },
  { cmd: "FWCV", want: /IT INCLUDES TERM PREMIUM/ },
  { cmd: "BTMM", want: /INDEX QUOTES THROUGH THE NORMAL QUOTE CHAIN/ },
  { cmd: "BTMM JP", want: /ONLY THE US CALENDAR \(BLS, BEA\) IS WIRED/ },
  { cmd: "WCRS", want: /CROSSES VS INR ARE COMPUTED/ },
  { cmd: "CDR", want: /FESTIVALS MISSING/ },
  { cmd: "CTM NG", want: /THE EXCHANGE'S OWN CALENDAR IS THE AUTHORITY/ },
  { cmd: "TSYS", want: /BUREAU OF THE FISCAL SERVICE/ },
  { cmd: "NRGF", want: /KEY REQUIRED: set EIA_API_KEY in APIKEYS/ },
  { cmd: "AGRI", want: /CORNELL MANN LIBRARY/ },
  { cmd: "RE", want: /ZILLOW RESEARCH DATA: NOT USED/ },
  { cmd: "WPE", want: /VALUES AS YAHOO FINANCE REPORTS THEM/ },
  // Phase 31: query language, field catalog, notebooks
  { cmd: "QRY last, mcap, sector FOR AAPL,MSFT WHERE mcap>1e12 SORT mcap", want: /A MISSING VALUE FAILS ITS WHERE CONDITION/ },
  { cmd: "QRY close, ret FOR AAPL,FRED:DGS10 DATES -6M..0 FREQ M", want: /W AND M ROWS ARE THE LAST VALUE/ },
  { cmd: "FLD valuation", want: /SNAPSHOT FIELDS GO WITHOUT DATES/ },
  { cmd: "NB", want: /NOT RUNNING/ },
  // Phase 25: OpenTerm Script (the list says how many starter examples ship)
  { cmd: "SCRIPT", want: /20 EXAMPLES/ },
  // wave 2: GP loads the script layer and says plainly when the named script is not saved (never a silent chart)
  { cmd: "AAPL GP SCRIPT=NOPE", want: /SCRIPT NOT FOUND: NOPE/ },
  // Phase 32
  { cmd: "RES SRC=BIS monetary", want: /NOT INCLUDED: IMF PAPERS/ },
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

// A panel can still have a request in flight through the /api/** forwarder when its assertion passes (FTS fires a second
// call); without this, that late route.fetch fails the finished test with "route.fetch: Test ended".
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

const BAD = /UNKNOWN FUNCTION|EMPTY PANEL|PROVIDER DOWN|NO DATA FOR|BAD (RANGE|INTERVAL)|ONLY AVAILABLE FOR/;

for (const c of CASES) {
  test(`smoke: ${c.cmd}`, async ({ page }) => {
    // The test's own limit (20 s in the config) must not be shorter than the wait it allows: BT OPT's first job starts a cold worker (~27 s).
    if (c.timeout) test.setTimeout(c.timeout + 30_000);
    const errors = await connect(page);
    await run(page, c.cmd);
    const p = panel(page);
    await expect(p).toContainText(c.want, { timeout: c.timeout ?? 15_000 });
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