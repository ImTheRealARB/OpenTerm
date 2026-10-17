// Runs the five gates at once (pytest, ruff, tsc, vitest, playwright) and prints one PASS/FAIL line each with its time.
// The suites are mostly waiting (worker spawns, browser start-up), so running them side by side is about 2x faster than
// one after another. Port 8000 / 4173 must be free (Playwright). Usage: node scripts/gates.mjs [--skip=e2e,pytest]
import { spawn } from "node:child_process";

process.noDeprecation = true; // `shell: true` is only for the .cmd shims on Windows; the arguments are fixed
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const skip = new Set((process.argv.find((a) => a.startsWith("--skip="))?.slice(7) ?? "").split(","));
const win = process.platform === "win32";
const npx = win ? "npx.cmd" : "npx";
const GATES = [
  { id: "pytest", cwd: "backend", cmd: "uv", args: ["run", "pytest", "-q"] },
  { id: "ruff", cwd: "backend", cmd: "uv", args: ["run", "ruff", "check", "."] },
  { id: "tsc", cwd: "frontend", cmd: npx, args: ["tsc", "--noEmit"] },
  { id: "vitest", cwd: "frontend", cmd: npx, args: ["vitest", "run"] },
  { id: "e2e", cwd: "frontend", cmd: npx, args: ["playwright", "test"], env: { CI: "1" } },
].filter((g) => !skip.has(g.id));

const t0 = Date.now();
const run = (g) =>
  new Promise((resolve) => {
    const start = Date.now();
    let out = "";
    const p = spawn(g.cmd, g.args, { cwd: join(root, g.cwd), env: { ...process.env, ...g.env }, shell: win });
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (out += d));
    p.on("close", (code) => resolve({ g, code, out, s: (Date.now() - start) / 1000 }));
  });

const results = await Promise.all(GATES.map(run));
for (const r of results) {
  const tail = r.out.trim().split(/\r?\n/).filter((l) => !l.includes("[WebServer]")).slice(-1)[0] ?? "";
  console.log(`${r.code === 0 ? "PASS" : "FAIL"}  ${r.g.id.padEnd(7)} ${r.s.toFixed(1).padStart(5)} s  ${tail.replace(/\x1b\[[0-9;]*m/g, "").slice(0, 90)}`);
}
const failed = results.filter((r) => r.code !== 0);
for (const r of failed) console.log(`\n--- ${r.g.id} ---\n${r.out.split(/\r?\n/).filter((l) => !l.includes("[WebServer]")).slice(-40).join("\n")}`);
console.log(`\n${failed.length ? "GATES FAILED" : "ALL GATES PASS"} in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
process.exit(failed.length ? 1 : 0);
