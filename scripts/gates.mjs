// Runs the five gates (ruff, tsc, pytest, vitest, playwright) and prints one PASS/FAIL line each with its time.
//   Stage 1, cheap and fail fast: ruff + tsc run side by side (a few seconds). If either fails, the heavy suites are skipped.
//   Stage 2, heavy: pytest + vitest + Playwright run side by side (they mostly wait on worker spawns and the browser, so this is
//   about 2x faster than one after another). Playwright needs ports 4173 (preview) and 8000 (unmocked requests) free: that is
//   checked first, and a busy port fails the e2e gate instead of silently testing another worktree's build.
// Usage: node scripts/gates.mjs [--skip=e2e,pytest] [--keep-going] [--e2e-last] [--list]
//   --keep-going  run the heavy suites even when ruff or tsc failed
//   --e2e-last    start Playwright only after pytest and vitest finished (slower; for a loaded machine, or if e2e flakes in parallel)
//   --list        print the plan and exit (nothing runs)
// Exit code: 0 all gates pass, 1 any gate failed. Output: one line per gate (in the order pytest, ruff, tsc, vitest, e2e), the last
// 40 lines of each failed gate, then `ALL GATES PASS in N s` or `GATES FAILED in N s`, with per-gate wall-clock times.
import { busyPorts, failureTail, npx, refused, root, run, summaryLine, timings } from "./lib/proc.mjs";

const argv = process.argv.slice(2);
const skip = new Set((argv.find((a) => a.startsWith("--skip="))?.slice(7) ?? "").split(",").filter(Boolean));
const keepGoing = argv.includes("--keep-going");
const e2eLast = argv.includes("--e2e-last");

const ALL = [
  { id: "pytest", stage: 2, cwd: "backend", cmd: "uv", args: ["run", "pytest", "-q"] },
  { id: "ruff", stage: 1, cwd: "backend", cmd: "uv", args: ["run", "ruff", "check", "."] },
  { id: "tsc", stage: 1, cwd: "frontend", cmd: npx, args: ["tsc", "--noEmit"] },
  { id: "vitest", stage: 2, cwd: "frontend", cmd: npx, args: ["vitest", "run"] },
  { id: "e2e", stage: 2, cwd: "frontend", cmd: npx, args: ["playwright", "test"], env: { CI: "1" }, ports: [4173, 8000] },
];
const GATES = ALL.filter((g) => !skip.has(g.id));
const cheap = GATES.filter((g) => g.stage === 1);
const heavy = GATES.filter((g) => g.stage === 2);
const heavyNow = e2eLast ? heavy.filter((g) => g.id !== "e2e") : heavy;
const heavyLater = e2eLast ? heavy.filter((g) => g.id === "e2e") : [];

if (argv.includes("--list")) {
  const names = (gs) => gs.map((g) => g.id).join(" + ") || "(none)";
  console.log(`root ${root}\nstage 1 (parallel, fail fast): ${names(cheap)}\nstage 2 (parallel): ${names(heavyNow)}\nstage 3 (after stage 2): ${names(heavyLater)}`);
  process.exit(0);
}

const t0 = Date.now();
const results = [];
const runGate = async (g) => {
  const why = g.ports ? await busyPorts(g.ports) : "";
  return why ? refused(g, why) : run(g);
};
const runAll = async (gs) => {
  const rs = await Promise.all(gs.map(runGate));
  results.push(...rs);
  return rs;
};

const stage1 = await runAll(cheap);
const stopped = !keepGoing && stage1.some((r) => r.code !== 0);
const skipped = stopped ? heavy.map((g) => g.id) : [];
if (!stopped) {
  await runAll(heavyNow);
  await runAll(heavyLater);
}

const order = ALL.map((g) => g.id);
results.sort((a, b) => order.indexOf(a.g.id) - order.indexOf(b.g.id));
for (const r of results) console.log(summaryLine(r));
for (const id of skipped) console.log(`SKIP  ${id.padEnd(7)}     -   not run: ruff or tsc failed (use --keep-going to run it anyway)`);
const failed = results.filter((r) => r.code !== 0);
for (const r of failed) console.log(failureTail(r));
console.log(`\n${failed.length ? "GATES FAILED" : "ALL GATES PASS"} in ${((Date.now() - t0) / 1000).toFixed(1)} s  (${timings(results)})`);
process.exit(failed.length ? 1 : 0);
