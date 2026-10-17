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
  add("Job J frame received to paint p95", ftp.n ? ftp.p95 : null, 50, "ms", `JOBS TEST; n=${ftp.n}`);
  add("Job submit p95, server-side (new + cached)", jobsServer, 20, "ms", "POST /api/jobs");
  add("Job submit to first J frame painted p95", jf.n ? jf.p95 : null, null, "ms", `via proxy; p50 ${jf.p50?.toFixed(1)} ms; n=${jf.n}`);
  add("Cached job (same hash) p95, server-side", jobs.cachedServer, 20, "ms", "POST /api/jobs, n=31");
  add("JOBS / APIKEYS open to first paint p95", r.p11.cmdToPaint.p95, 100, "ms", `n=${r.p11.cmdToPaint.n}`);
  add("Worker pool cold start (first job done)", jobs.coldMs, null, "ms", "spawn; measured, not gated");

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
