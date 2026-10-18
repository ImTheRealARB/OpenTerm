#!/usr/bin/env node
/**
 * OpenTerm performance bench. Measures the PERFORMANCE SPEC budgets and exits 1 on any FAIL.
 * Budgets that need features not built yet report N/A with the phase that enables them;
 * N/A never counts as a pass in the release checklist.
 *
 *   node scripts/bench.mjs            build + run
 *   node scripts/bench.mjs --no-build reuse frontend/dist
 */
import { spawn, execSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { createRequire } from "node:module";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const FE = join(ROOT, "frontend");
const BE = join(ROOT, "backend");
const require = createRequire(join(FE, "package.json"));
const { chromium } = require("@playwright/test");

const BACKEND = "http://127.0.0.1:8000";
const FRONTEND = "http://127.0.0.1:4173";
const isWin = process.platform === "win32";
const children = [];

const results = [];
const add = (metric, value, budget, unit, note = "") => {
  const status = value === null ? "N/A" : budget === null ? "INFO" : value <= budget ? "PASS" : "FAIL";
  results.push({ metric, value, budget, unit, status, note });
};
const p95 = (a) => (a.length ? [...a].sort((x, y) => x - y)[Math.round(0.95 * (a.length - 1))] : NaN);

function start(cmd, cwd, env = {}) {
  const child = spawn(cmd, { cwd, shell: true, stdio: "ignore", env: { ...process.env, ...env } });
  children.push(child);
  return child;
}

function stopAll() {
  for (const c of children) {
    try {
      if (isWin) execSync(`taskkill /pid ${c.pid} /T /F`, { stdio: "ignore" });
      else process.kill(-c.pid);
    } catch {
      c.kill();
    }
  }
}

async function waitFor(url, ms = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`timeout waiting for ${url}`);
}

function bundleSize() {
  const dist = join(FE, "dist");
  const html = readFileSync(join(dist, "index.html"), "utf8");
  // Initial = entry script + modulepreloads + CSS referenced from index.html.
  const refs = [...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.(?:js|css))"/g)].map((m) => m[1]);
  return refs.reduce((sum, f) => sum + gzipSync(readFileSync(join(dist, f))).length, 0) / 1024;
}

async function backendP95(path = "/api/health") {
  const lat = [];
  for (let i = 0; i < 20; i++) await (await fetch(`${BACKEND}${path}`)).arrayBuffer(); // warm
  for (let i = 0; i < 300; i++) {
    const t0 = performance.now();
    await (await fetch(`${BACKEND}${path}`)).arrayBuffer();
    lat.push(performance.now() - t0);
  }
  // Server-side time is the gate: Node fetch on Windows loopback adds a ~15.6 ms timer-tick
  // artifact (a keep-alive Python client sees <1 ms), so client time is reported as a note only.
  const server = (await (await fetch(`${BACKEND}/api/perf`)).json())[path.split("?")[0]].p95;
  return { server, client: p95(lat) };
}

/** Phase 11: first job starts the worker pool (cold, reported); then identical submits return the cached result. */
async function jobsBench() {
  const post = async () => (await fetch(`${BACKEND}/api/jobs`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ kind: "sleep", params: { steps: 1, step_ms: 1, tag: "bench" } }),
  })).json();
  const t0 = performance.now();
  const first = await post();
  for (let i = 0; i < 600; i++) {
    const j = await (await fetch(`${BACKEND}/api/jobs/${first.id}`)).json();
    if (j.state === "done") break;
    if (j.state === "error" || j.state === "cancelled") throw new Error(`bench job ended ${j.state}: ${j.error}`);
    await new Promise((r) => setTimeout(r, 20));
  }
  const coldMs = performance.now() - t0;
  for (let i = 0; i < 30; i++) {
    const j = await post();
    if (!j.cached) throw new Error("repeated bench job was not served from the cache");
  }
  const cachedServer = (await (await fetch(`${BACKEND}/api/perf`)).json())["/api/jobs"].p95;
  return { coldMs, cachedServer };
}

/** Phase 12: BT runs on 10 years of daily fixture bars. Server time per request comes from the `server-timing`
 * header (Node fetch on Windows loopback adds ~16 ms); job time is the job's own created_at -> finished_at. */
async function btBench() {
  const post = async (body) => {
    const res = await fetch(`${BACKEND}/api/bt/run`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    const serverMs = Number(/dur=([\d.]+)/.exec(res.headers.get("server-timing") ?? "")?.[1]);
    const j = await res.json();
    if (!res.ok) throw new Error(`bt run failed: ${j.error}${j.detail ? ` (${j.detail})` : ""}`);
    return { j, serverMs };
  };
  const done = async (id) => {
    for (let i = 0; i < 3000; i++) {
      const j = await (await fetch(`${BACKEND}/api/jobs/${id}`)).json();
      if (j.state === "done") return j;
      if (j.state === "error" || j.state === "cancelled") throw new Error(`bt job ended ${j.state}: ${j.error}`);
      await new Promise((r) => setTimeout(r, 5));
    }
    throw new Error("bt job did not finish in time");
  };
  const req = (rule, symbols = ["AAPL"]) => ({ rule, symbols, interval: "1D", range: "10Y", options: {} });

  const t0 = performance.now();
  const first = await post(req("SMA20>SMA50"));
  await done(first.j.id);
  const coldMs = performance.now() - t0; // pandas import in a fresh worker + the first bar fetch
  // Warm every worker: rounds of concurrent distinct runs (a worker imports pandas on its first BT job).
  for (let k = 0; k < 2; k++) {
    const js = await Promise.all([0, 1, 2, 3].map((i) => post(req(`SMA${5 + i + k * 4}>SMA60`))));
    await Promise.all(js.map((x) => done(x.j.id)));
  }
  const runs = [];
  for (let i = 0; i < 12; i++) {
    const { j, serverMs } = await post(req(`EMA${10 + i}>SMA100`));
    const d = await done(j.id);
    runs.push(serverMs + (d.finished_at - d.created_at) * 1000);
  }
  const cached = [];
  for (let i = 0; i < 30; i++) {
    const { j, serverMs } = await post(req("EMA10>SMA100"));
    if (!j.cached) throw new Error("repeated BT run was not served from the cache");
    cached.push(serverMs);
  }
  // 100 symbols x 10 years: synthetic bars (SYN0000-SYN0099). Measured, not gated.
  let big = null, bigNote = "";
  try {
    const syms = Array.from({ length: 100 }, (_, i) => `SYN${String(i).padStart(4, "0")}`);
    const b0 = performance.now();
    const { j } = await post(req("SMA20>SMA50", syms));
    await done(j.id);
    big = performance.now() - b0;
    bigNote = "SYN0000-SYN0099, end to end incl. bar fetch";
  } catch (e) {
    bigNote = `not measured: ${String(e.message ?? e).slice(0, 60)}`;
  }
  return { coldMs, run: p95(runs), cached: p95(cached), big, bigNote };
}

/** Phase 15: RISK, PORT OPT, ALPHA and CORR REGIME on SYN names (fixture + synthetic mode), through POST /api/quant/{fn}.
 * Like the BT budgets, the figure is server-side: `server-timing` of the POST (parse, cached bars, data file, submit) plus the job's own
 * created_at -> finished_at, on warm workers. Every measured run uses a distinct parameter (conf, rf, edge, h) so none is a cache hit. */
async function aiBench() {
  const key = await fetch(`${BACKEND}/api/keys/openrouter`, {
    method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ fields: { OPENROUTER_API_KEY: "sk-or-bench-0000000000000000" } }),
  });
  if (!key.ok) throw new Error(`bench could not set the fake AI key: HTTP ${key.status}`);
  const N = 12;
  for (let i = 0; i < N; i++) {
    const res = await fetch(`${BACKEND}/api/ai/chat`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: `What is AAPL trading at? (${i})` }),
    });
    const text = await res.text();
    const done = text.split("\n\n").map((b) => b.replace(/^data: /, "")).filter((b) => b.startsWith("{")).map((b) => JSON.parse(b)).find((e) => e.type === "done");
    if (!done || !done.grounded) throw new Error(`AI bench turn ${i} did not finish grounded: ${text.slice(0, 200)}`);
  }
  const p = (await (await fetch(`${BACKEND}/api/perf`)).json())["/api/ai/first_event"];
  return { firstEvent: p?.p95 ?? null, n: p?.n ?? 0 };
}

async function quantBench() {
  const post = async (fn, body) => {
    const res = await fetch(`${BACKEND}/api/quant/${fn}`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    const serverMs = Number(/dur=([\d.]+)/.exec(res.headers.get("server-timing") ?? "")?.[1]);
    const j = await res.json();
    if (!res.ok) throw new Error(`quant ${fn} failed: ${j.error}${j.detail ? ` (${j.detail})` : ""}`);
    return { j, serverMs };
  };
  const done = async (id) => {
    for (let i = 0; i < 6000; i++) {
      const j = await (await fetch(`${BACKEND}/api/jobs/${id}`)).json();
      if (j.state === "done") return j;
      if (j.state === "error" || j.state === "cancelled") throw new Error(`quant job ended ${j.state}: ${j.error}`);
      await new Promise((r) => setTimeout(r, 5));
    }
    throw new Error("quant job did not finish in time");
  };
  const one = async (fn, body) => {
    const { j, serverMs } = await post(fn, body);
    if (j.cached) throw new Error(`quant ${fn} run was served from the cache; the bench needs a distinct parameter`);
    const d = await done(j.id);
    if (d.result?.data?.not_runnable || d.result?.not_runnable) throw new Error(`quant ${fn} NOT RUNNABLE`);
    return serverMs + (d.finished_at - d.created_at) * 1000;
  };
  const syn = (n) => Array.from({ length: n }, (_, i) => `SYN${String(i).padStart(4, "0")}`);
  const put = await fetch(`${BACKEND}/api/portfolios/BENCH15`, {
    method: "PUT", headers: { "content-type": "application/json" },
    body: JSON.stringify({ positions: syn(20).map((symbol, i) => ({ symbol, qty: 10 + i, cost: 100 })) }),
  });
  if (!put.ok) throw new Error(`could not create the bench portfolio: ${put.status}`);
  const pf = "BENCH15";
  const risk = (i) => ({ portfolio: pf, range: "3Y", bench: "SYN0001", conf: 90 + i * 0.05 });
  const opt = (method, i) => ({ portfolio: pf, method, lookback: 252, rf: i * 0.0005 });
  const regime = (i) => ({ symbols: syn(20), win: 60, edge: 0.3 + i * 0.01, range: "2Y" });

  // Warm every worker (each imports pandas and scipy on its first job) and the bar cache: concurrent distinct runs of each kind.
  for (let k = 0; k < 2; k++) {
    const js = await Promise.all([0, 1, 2, 3].map((i) => post("risk", risk(100 + k * 4 + i))));
    await Promise.all(js.map((x) => done(x.j.id)));
    const os = await Promise.all([0, 1, 2, 3].map((i) => post("opt", opt(i % 2 ? "HRP" : "RP", 100 + k * 4 + i))));
    await Promise.all(os.map((x) => done(x.j.id)));
    const rs = await Promise.all([0, 1, 2, 3].map((i) => post("regime", regime(50 + k * 4 + i))));
    await Promise.all(rs.map((x) => done(x.j.id)));
  }
  const riskRuns = [], hrpRuns = [], rpRuns = [], regimeRuns = [];
  for (let i = 0; i < 12; i++) riskRuns.push(await one("risk", risk(i)));
  for (let i = 0; i < 12; i++) hrpRuns.push(await one("opt", opt("HRP", i)));
  for (let i = 0; i < 12; i++) rpRuns.push(await one("opt", opt("RP", i)));
  for (let i = 0; i < 12; i++) regimeRuns.push(await one("regime", regime(i)));
  // ALPHA: SYN 100 names x 2 years, all families. One warm-up run (bar fetch), then 3 runs with distinct horizons.
  const alpha = (h) => ({ universe: "SYN", range: "2Y", h });
  await one("alpha", alpha("1,5,10,20,40"));
  const alphaRuns = [];
  for (const h of ["1,5,10,20", "1,5,10", "1,5,20"]) alphaRuns.push(await one("alpha", alpha(h)));
  return { risk: p95(riskRuns), hrp: p95(hrpRuns), rp: p95(rpRuns), regime: p95(regimeRuns), alpha: p95(alphaRuns), alphaN: alphaRuns.length };
}

async function freshPage(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await ctx.newPage();
  await page.goto(FRONTEND);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForFunction(() => window.__openterm_perf?.ready);
  await page.waitForTimeout(500); // idle preload of modules
  return page;
}

async function run(page, text) {
  await page.keyboard.press("Control+k");
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
}

/** Runs fn with fresh measurement windows and the frame sampler on; returns the perf snapshot. */
async function measure(page, fn) {
  await page.evaluate(() => window.__openterm_perf.reset());
  const stop = await page.evaluateHandle(() => window.__openterm_perf.watchFrames());
  await fn();
  const snap = await page.evaluate(() => window.__openterm_perf.snapshot());
  await page.evaluate((s) => s(), stop);
  return snap;
}

async function browserBench() {
  const browser = await chromium.launch({ args: ["--enable-precise-memory-info"] });
  try {
    // Cold start: fresh context, empty cache.
    const cold = [];
    for (let i = 0; i < 5; i++) {
      const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
      const page = await ctx.newPage();
      await page.goto(FRONTEND);
      await page.waitForFunction(() => window.__openterm_perf?.ready);
      cold.push(await page.evaluate(() => window.__openterm_perf.ready));
      await ctx.close();
    }

    const out = { cold: p95(cold) };

    // A. Keystrokes, cached commands, 8 panels.
    {
      const page = await freshPage(browser);
      out.a = await measure(page, async () => {
        await page.keyboard.press("Control+k");
        await page.keyboard.type("AAPL US EQUITY GP 1Y D VS SPY QQQ", { delay: 25 });
        await page.keyboard.press("Control+a");
        await page.keyboard.press("Backspace");
        const cmds = ["HELP", "SHORTCUTS", "PERF", "HELP GP", "SOURCES", "LOG"];
        for (let i = 0; i < 4; i++) {
          for (const c of cmds) {
            await page.keyboard.type(c);
            await page.keyboard.press("Enter");
            await page.waitForTimeout(30);
          }
        }
        for (let i = 0; i < 7; i++) {
          await page.keyboard.press("Control+\\");
          await run(page, i % 2 ? "PERF" : "HELP");
          await page.waitForTimeout(50);
        }
        await page.waitForTimeout(1500);
      });
      await page.context().close();
    }

    // B. Cold network: backend fixtures answer after 300 ms; the panel skeleton must paint first.
    {
      const page = await freshPage(browser);
      for (let i = 0; i < 10; i++) {
        await run(page, `ZZQ${i} DES`);
        await page.waitForTimeout(700);
      }
      const log = await page.evaluate(() => window.__openterm_perf.commandLog.map((c) => c.ms));
      out.coldCmd = { p95: p95(log), n: log.length };
      await page.context().close();
    }

    // C. Streaming load: 200 SYNTHETIC symbols x 20 ticks/s across 9 Q panels (the UI maximum).
    {
      const page = await freshPage(browser);
      const syms = Array.from({ length: 200 }, (_, i) => `SYN${String(i).padStart(4, "0")}`);
      const per = Math.ceil(syms.length / 9);
      for (let pnl = 0; pnl < 9; pnl++) {
        if (pnl > 0) await page.keyboard.press(pnl % 2 ? "Control+\\" : "Control+-");
        await run(page, `Q ${syms.slice(pnl * per, (pnl + 1) * per).join(" ")}`);
        await page.waitForTimeout(150);
      }
      await page.waitForTimeout(2500); // snapshots + subscriptions settle
      out.stream = await measure(page, async () => {
        await page.waitForTimeout(1500);
        await page.keyboard.press("Control+k");
        await page.keyboard.type("TYPING WHILE 4000 TICKS PER SECOND ARRIVE", { delay: 30 });
        await page.keyboard.press("Escape");
        await page.waitForTimeout(3000);
      });
      await page.context().close();
    }

    // F. Named layouts through the real backend (SQLite): alternate a 9-panel and a 1-panel layout.
    {
      const page = await freshPage(browser);
      const fns = ["HELP", "PERF", "SOURCES", "LOG", "AAPL DES", "AAPL QR", "Q SYN0001 SYN0002 SYN0003", "SHORTCUTS", "LAYOUT"];
      await run(page, fns[0]);
      for (let i = 1; i < 9; i++) {
        await page.keyboard.press(i % 2 ? "Control+\\" : "Control+-");
        await run(page, fns[i]);
        await page.waitForTimeout(100);
      }
      await run(page, "LAYOUT SAVE BENCH9");
      await page.waitForTimeout(300);
      for (let i = 0; i < 8; i++) await page.keyboard.press("Alt+w");
      await run(page, "LAYOUT SAVE BENCH1");
      await page.waitForTimeout(300);
      out.layout = await measure(page, async () => {
        for (let i = 0; i < 20; i++) {
          await run(page, `LAYOUT LOAD ${i % 2 ? "BENCH1" : "BENCH9"}`);
          await page.waitForTimeout(250);
        }
      });
      await page.context().close();
    }

    // G. Phase 11: JOBS / APIKEYS open (cached-command budget) and submit to first painted J frame (warm pool).
    {
      const page = await freshPage(browser);
      out.p11 = await measure(page, async () => {
        for (let i = 0; i < 10; i++) {
          await run(page, `JOBS TEST ${i + 2} 1`);
          await page.waitForTimeout(250);
        }
        for (let i = 0; i < 10; i++) {
          await run(page, i % 2 ? "APIKEYS" : "JOBS");
          await page.waitForTimeout(150);
        }
      });
      await page.context().close();
    }

    // G2. Phase 16: AI panel open (typed command to the input ready).
    {
      const page = await freshPage(browser);
      out.p16 = await measure(page, async () => {
        for (let i = 0; i < 10; i++) {
          await run(page, "AI");
          await page.waitForTimeout(200);
        }
      });
      await page.context().close();
    }

    // H. Phase 12: BT result open (cached runs from btBench) to the painted, labelled result.
    {
      const page = await freshPage(browser);
      out.p12 = await measure(page, async () => {
        for (let i = 0; i < 20; i++) {
          await run(page, i % 2 ? "BT AAPL EMA10>SMA100 1D 10Y" : "BT AAPL SMA20>SMA50 1D 10Y");
          await page.waitForTimeout(300);
          await page.keyboard.press("Escape");
        }
      });
      await page.context().close();
    }

    // D. 10,000-row canvas grid: keyboard paging + wheel scrolling.
    {
      const page = await freshPage(browser);
      await run(page, "PERF GRID 10000");
      await page.waitForTimeout(500);
      await page.keyboard.press("Escape");
      const box = await page.locator('[data-panel="1"] canvas').boundingBox();
      out.grid = await measure(page, async () => {
        for (let i = 0; i < 120; i++) await page.keyboard.press(i % 40 < 30 ? "PageDown" : "j");
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        for (let i = 0; i < 80; i++) await page.mouse.wheel(0, i % 20 < 15 ? 120 : -120);
        await page.waitForTimeout(300);
      });
      await page.context().close();
    }

    // E. 50,000-bar chart: zoomed out, keyboard panning and zooming.
    {
      const page = await freshPage(browser);
      await run(page, "PERF CHART 50000");
      await page.waitForTimeout(1500);
      await page.keyboard.press("Escape");
      for (let i = 0; i < 6; i++) await page.keyboard.press("-");
      out.chart = await measure(page, async () => {
        for (let i = 0; i < 150; i++) await page.keyboard.press(i % 50 < 25 ? "ArrowLeft" : "ArrowRight");
        for (let i = 0; i < 20; i++) await page.keyboard.press(i % 2 ? "+" : "-");
        await page.waitForTimeout(300);
      });
      await page.context().close();
    }
    // I. Phase 19: chart maths (patterns + SMC on 5,000 bars, SEAS on 10,000 daily bars), generated TEST DATA.
    {
      const page = await freshPage(browser);
      await run(page, "PERF CALC");
      await page.waitForFunction(() => window.__openterm_perf?.snapshot?.().gauges?.["p19.patternsMs"] !== undefined, null, { timeout: 15000 }).catch(() => {});
      out.p19 = await page.evaluate(() => window.__openterm_perf.snapshot().gauges);
      await page.context().close();
    }
    return out;
  } finally {
    await browser.close();
  }
}

async function main() {
  if (!process.argv.includes("--no-build")) {
    execSync("npm run build", { cwd: FE, stdio: "ignore" });
  }
  if (!existsSync(join(FE, "dist", "index.html"))) throw new Error("frontend/dist missing");

  // Fixture mode: recorded provider responses, so the bench never depends on (or hammers) Yahoo.
  const dbDir = mkdtempSync(join(tmpdir(), "openterm-bench-"));
  start("uv run python -m openterm", BE, {
    OPENTERM_FIXTURES: "1",
    OPENTERM_SYNTHETIC: "1",
    OPENTERM_SYNTHETIC_TPS: "20",
    OPENTERM_FIXTURE_LATENCY_MS: "300",
    OPENTERM_DB_PATH: join(dbDir, "bench.db"),
    OPENTERM_KEYRING: "memory", // the bench sets a fake OpenRouter key for the AI budget: never the real keyring
    OPENTERM_DOTENV_PATH: join(dbDir, "keys.env"),
  });
  start("npm run preview -- --host 127.0.0.1", FE);
  await waitFor(`${BACKEND}/api/health`);
  await waitFor(FRONTEND);

  add("Initial JS+CSS bundle (gzip)", bundleSize(), 400, "KB");
  for (const path of ["/api/health", "/api/quote?symbols=AAPL,MSFT,RELIANCE.NS", "/api/history?symbol=AAPL&range=1Y"]) {
    const be = await backendP95(path);
    add(`Backend p95, cached ${path.split("?")[0]}`, be.server, 20, "ms", `server-side; node client ${be.client.toFixed(1)} ms`);
  }

  const jobs = await jobsBench(); // warms the worker pool before the browser section G
  const bt = await btBench(); // caches the runs section H opens

  const r = await browserBench();
  const { a, stream: st } = r;
  add("Cold start to usable command line (web)", r.cold, 1500, "ms", "p95 of 5 fresh contexts");
  add("Keystroke to echo p95 (keydown to next frame)", a.keyEcho.p95, 16.7, "ms", `one 60Hz frame; n=${a.keyEcho.n}`);
  add("Command submit to first paint, cached, p95", a.cmdToPaint.p95, 100, "ms", `n=${a.cmdToPaint.n}`);
  add("Frame time p95, 8-panel workload", a.frameP95, 20, "ms", "60Hz vsync = 16.7; >25 = dropped frame");
  add("Command submit to first paint, cold network, p95", r.coldCmd.p95, 400, "ms", `skeleton; upstream 300 ms; n=${r.coldCmd.n}`);
  add("Tick received to pixel p95, streaming load", st.tickToPixel.p95, 50, "ms", `200 SYN x 20/s, 9 panels; n=${st.tickToPixel.n}`);
  add("Frame time p95, streaming load", st.frameP95, 20, "ms", "same load");
  add("Keystroke echo p95, streaming load", st.keyEcho.p95, 16.7, "ms", `typing during load; n=${st.keyEcho.n}`);
  add("Long tasks (>50 ms), streaming load", st.longTasks, 0, "", "UI never freezes");
  add("JS heap, 9 panels + 200 streaming symbols", st.heapMB, 500, "MB", "JS heap only (see PERFORMANCE.md)");
  add("Ticks delivered to the page per second", st.gauges["ws.ticksPerSec"] ?? 0, null, "/s", "offered: 200 x 20 = 4000/s");
  add("Layout load to paint p95 (SQLite, 9 / 1 panels)", r.layout.layoutLoad.p95, 100, "ms", `n=${r.layout.layoutLoad.n}; frame p95 ${r.layout.frameP95.toFixed(1)} ms`);
  add("Frame time p95, 10k-row grid scroll", r.grid.frameP95, 20, "ms", "keys + wheel");
  add("Frame time p95, 50k-bar chart pan/zoom", r.chart.frameP95, 20, "ms", "keys");
  // Job budgets are split like backend latency: browser frame-to-paint and server time are gated; end to end goes
  // through the Vite preview proxy (Node on Windows loopback adds ~16 ms) and is reported only.
  const jf = r.p11.jobsFirstFrame ?? { p95: null, n: 0 };
  const ftp = r.p11.jobsFrameToPaint ?? { p95: null, n: 0 };
  const jobsServer = (await (await fetch(`${BACKEND}/api/perf`)).json())["/api/jobs"].p95;
  // Phase 15 server-side job times. Run AFTER the line above: quantBench polls GET /api/jobs/{id}, which /api/perf files under /api/jobs.
  const q15 = await quantBench();
  const ai16 = await aiBench();
  add("Job J frame received to paint p95", ftp.n ? ftp.p95 : null, 50, "ms", `JOBS TEST; n=${ftp.n}`);
  add("Job submit p95, server-side (new + cached)", jobsServer, 20, "ms", "POST /api/jobs");
  add("Job submit to first J frame painted p95", jf.n ? jf.p95 : null, null, "ms", `via proxy; p50 ${jf.p50?.toFixed(1)} ms; n=${jf.n}`);
  add("Cached job (same hash) p95, server-side", jobs.cachedServer, 20, "ms", "POST /api/jobs, n=31");
  add("JOBS / APIKEYS open to first paint p95", r.p11.cmdToPaint.p95, 100, "ms", `n=${r.p11.cmdToPaint.n}`);
  add("Worker pool cold start (first job done)", jobs.coldMs, null, "ms", "spawn; measured, not gated");
  add("BT 10-year daily rule run p95, server-side", bt.run, 300, "ms", "POST + job created->finished, warm worker, n=12");
  add("BT cached run (same hash) p95, server-side", bt.cached, 20, "ms", "POST /api/bt/run, n=30");
  const bo = r.p12.btOpen ?? { p95: null, n: 0 };
  const g = (k) => (r.p12.gauges[k] ?? NaN).toFixed(1);
  add("BT result open to first paint p95", bo.n ? bo.p95 : null, 100, "ms", `cached run; n=${bo.n}; p50 ${bo.p50?.toFixed(1)}; last: post ${g("bt.postMs")} get ${g("bt.getMs")} render ${g("bt.renderMs")} ms`);
  add("BT first run, cold worker (pandas import)", bt.coldMs, null, "ms", "measured, not gated");
  add("BT 100 symbols x 10 years", bt.big, null, "ms", bt.bigNote);
  // Phase 15 (spec decision M): server-side like the BT budgets (POST server-timing + job created->finished, warm workers).
  add("RISK 20 names x 3 years p95, server-side", q15.risk, 400, "ms", "POST /api/quant/risk + job, warm, SYN0000-SYN0019, n=12");
  add("PORT OPT HRP 20 names p95, server-side", q15.hrp, 400, "ms", "POST /api/quant/opt + job, warm, 252-day lookback, n=12");
  add("PORT OPT RP 20 names p95, server-side", q15.rp, 400, "ms", "POST /api/quant/opt + job, warm, 252-day lookback, n=12");
  add("CORR REGIME 20 names x 2 years p95, server-side", q15.regime, 300, "ms", "POST /api/quant/regime + job, warm, n=12");
  add("ALPHA SYN 100 names x 2 years, server-side", q15.alpha, 8000, "ms", `POST /api/quant/alpha + job, all 29 factors, warm; n=${q15.alphaN} (p95 = slowest)`);

  // Phase 16 (spec: decisions on the first-token budget): what this server controls. Fixture mode replays a recorded model.
  add("AI request to first SSE event p95, server-side", ai16.firstEvent, 60, "ms", `POST /api/ai/chat, recorded model, n=${ai16.n}`);
  add("AI panel open to first paint p95", r.p16.cmdToPaint.p95, 100, "ms", `n=${r.p16.cmdToPaint.n}`);

  // Phase 19 budgets (spec): chart maths in the page, p95 of 15 runs on generated bars.
  add("Pattern scan (candles + SMC) 5,000 bars p95", r.p19["p19.patternsMs"] ?? null, 40, "ms", "PERF CALC, TEST DATA");
  add("SEAS MONTH+WOY+DOM 10,000 daily bars p95", r.p19["p19.seasMs"] ?? null, 15, "ms", "PERF CALC, TEST DATA");
  add("Drawing hit test, 200 drawings p95", r.p19["p19.hitMs"] ?? null, 1, "ms", "PERF CALC, TEST DATA");
  add("IMAP treemap layout, 5,000 tiles p95", r.p19["p19.treemapMs"] ?? null, 30, "ms", "PERF CALC, TEST DATA");
  add("IMAP canvas paint, 5,000 tiles p95", r.p19["p19.imapPaintMs"] ?? null, 16, "ms", "PERF CALC, 1600x900, TEST DATA");

  const pad = (s, n) => String(s).padEnd(n);
  console.log("\n" + pad("METRIC", 52) + pad("VALUE", 12) + pad("BUDGET", 12) + pad("STATUS", 8) + "NOTE");
  for (const r of results) {
    const v = r.value === null ? "-" : `${r.value.toFixed(1)} ${r.unit}`;
    console.log(pad(r.metric, 52) + pad(v, 12) + pad(r.budget === null ? "-" : `${r.budget} ${r.unit}`, 12) + pad(r.status, 8) + r.note);
  }
  writeFileSync(join(ROOT, "bench-report.json"), JSON.stringify({ at: new Date().toISOString(), results }, null, 2));
  const failed = results.filter((r) => r.status === "FAIL");
  console.log(`\n${failed.length ? "FAIL" : "PASS"}: ${results.filter((r) => r.status === "PASS").length} pass, ${failed.length} fail, ${results.filter((r) => r.status === "N/A").length} n/a`);
  return failed.length ? 1 : 0;
}

let code = 1;
try {
  code = await main();
} catch (e) {
  console.error(e);
} finally {
  stopAll();
  process.exit(code);
}
