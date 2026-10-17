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
  const status = value === null ? "N/A" : value <= budget ? "PASS" : "FAIL";
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

    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const page = await ctx.newPage();
    await page.goto(FRONTEND);
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForFunction(() => window.__openterm_perf?.ready);
    await page.waitForTimeout(500); // idle preload of modules

    const stopFrames = await page.evaluateHandle(() => window.__openterm_perf.watchFrames());

    // Keystroke echo.
    await page.keyboard.press("Control+k");
    await page.keyboard.type("AAPL US EQUITY GP 1Y D VS SPY QQQ", { delay: 25 });
    await page.keyboard.press("Control+a");
    await page.keyboard.press("Backspace");

    // Command submit -> first paint (cached modules), plus an 8-panel workload.
    const cmds = ["HELP", "SHORTCUTS", "PERF", "HELP GP", "AAPL GP", "MSFT DES"];
    for (let i = 0; i < 4; i++) {
      for (const c of cmds) {
        await page.keyboard.type(c);
        await page.keyboard.press("Enter");
        await page.waitForTimeout(30);
      }
    }
    for (let i = 0; i < 7; i++) {
      await page.keyboard.press("Control+\\");
      await page.keyboard.press("Control+k");
      await page.keyboard.type(i % 2 ? "PERF" : "HELP");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(50);
    }
    await page.waitForTimeout(1500);
    const snap = await page.evaluate(() => window.__openterm_perf.snapshot());
    await page.evaluate((stop) => stop(), stopFrames);
    return { cold: p95(cold), snap };
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
  start("uv run python -m openterm", BE, { OPENTERM_FIXTURES: "1", OPENTERM_DB_PATH: join(dbDir, "bench.db") });
  start("npm run preview -- --host 127.0.0.1", FE);
  await waitFor(`${BACKEND}/api/health`);
  await waitFor(FRONTEND);

  add("Initial JS+CSS bundle (gzip)", bundleSize(), 400, "KB");
  for (const path of ["/api/health", "/api/quote?symbols=AAPL,MSFT,RELIANCE.NS", "/api/history?symbol=AAPL&range=1Y"]) {
    const be = await backendP95(path);
    add(`Backend p95, cached ${path.split("?")[0]}`, be.server, 20, "ms", `server-side; node client ${be.client.toFixed(1)} ms`);
  }

  const { cold, snap } = await browserBench();
  add("Cold start to usable command line (web)", cold, 1500, "ms", "p95 of 5 fresh contexts");
  add("Keystroke to echo p95 (keydown to next frame)", snap.keyEcho.p95, 16.7, "ms", `one 60Hz frame; n=${snap.keyEcho.n}`);
  add("Command submit to first paint, cached, p95", snap.cmdToPaint.p95, 100, "ms", `n=${snap.cmdToPaint.n}`);
  add("Frame time p95 under 8-panel workload", snap.frameP95, 20, "ms", "60Hz vsync = 16.7; >25 = dropped frame");
  add("JS heap with 8 panels", snap.heapMB, 500, "MB", "no streaming yet");
  add("Command submit to first paint, cold network", null, 400, "ms", "needs a data-rendering function (phase 3)");
  add("Tick received to pixel p95", null, 50, "ms", "needs streaming (phase 3)");
  add("60 fps scroll, 10k-row grid", null, 16.7, "ms", "needs canvas grid (phase 3)");
  add("60 fps pan, 50k-bar chart", null, 16.7, "ms", "needs GP (phase 3)");
  add("Memory, 8 panels + 100 streaming symbols", null, 500, "MB", "needs streaming (phase 3)");
  add("Synthetic load 200 sym x 20 ticks/s, 10 panels", null, 16.7, "ms", "needs streaming (phase 3)");

  const pad = (s, n) => String(s).padEnd(n);
  console.log("\n" + pad("METRIC", 52) + pad("VALUE", 12) + pad("BUDGET", 12) + pad("STATUS", 8) + "NOTE");
  for (const r of results) {
    const v = r.value === null ? "-" : `${r.value.toFixed(1)} ${r.unit}`;
    console.log(pad(r.metric, 52) + pad(v, 12) + pad(`${r.budget} ${r.unit}`, 12) + pad(r.status, 8) + r.note);
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
