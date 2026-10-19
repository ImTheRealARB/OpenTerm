// Shared helpers for scripts/gates.mjs and scripts/check.mjs: run one gate as a child process, probe a port.
import { spawn } from "node:child_process";
import net from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

process.noDeprecation = true; // `shell: true` is only for the .cmd shims on Windows; the arguments are fixed

export const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const win = process.platform === "win32";
export const npx = win ? "npx.cmd" : "npx";
export const stripAnsi = (s) => s.replace(/\x1b\[[0-9;]*m/g, "");
const noise = (l) => l.includes("[WebServer]");

/** Runs `g` ({id, cwd, cmd, args, env?}) to the end; never rejects. Resolves {g, code, out, s}. */
export function run(g) {
  return new Promise((resolve) => {
    const start = Date.now();
    let out = "";
    const done = (code) => resolve({ g, code, out, s: (Date.now() - start) / 1000 });
    const p = spawn(g.cmd, g.args, { cwd: join(root, g.cwd), env: { ...process.env, ...g.env }, shell: win });
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (out += d));
    p.on("error", (e) => {
      out += String(e);
      done(1);
    });
    p.on("close", (code) => done(code ?? 1));
  });
}

/** A result that never ran (for example a port was busy): counts as a failure with the reason as its output. */
export const refused = (g, why) => ({ g, code: 1, out: why, s: 0 });

/** True when something already listens on `port` (IPv4 or IPv6 loopback). */
export function portBusy(port) {
  const probe = (host) =>
    new Promise((resolve) => {
      const sock = net.connect({ port, host });
      const end = (busy) => {
        sock.destroy();
        resolve(busy);
      };
      sock.setTimeout(500, () => end(false));
      sock.once("connect", () => end(true));
      sock.once("error", () => end(false));
    });
  return Promise.all([probe("127.0.0.1"), probe("::1")]).then((r) => r.some(Boolean));
}

/** Names the busy ports among `ports`, or "" when all are free. Playwright (4173) and the unmocked e2e requests (8000) need them. */
export async function busyPorts(ports) {
  const busy = [];
  for (const p of ports) if (await portBusy(p)) busy.push(p);
  return busy.length
    ? `port ${busy.join(", ")} already in use (another worktree's preview or backend?): Playwright would silently test that build. Stop it and rerun.`
    : "";
}

/** One summary line for a result: `PASS  pytest   42.1 s  <last output line>` (same format gates.mjs always printed). */
export function summaryLine(r) {
  const lines = r.out.trim().split(/\r?\n/).filter((l) => !noise(l));
  const tail = stripAnsi(lines[lines.length - 1] ?? "").slice(0, 90);
  return `${r.code === 0 ? "PASS" : "FAIL"}  ${r.g.id.padEnd(7)} ${r.s.toFixed(1).padStart(5)} s  ${tail}`;
}

/** The last 40 lines of a failed gate's output. */
export function failureTail(r) {
  return `\n--- ${r.g.id} ---\n${r.out.split(/\r?\n/).filter((l) => !noise(l)).slice(-40).join("\n")}`;
}

/** `ruff 2.1 s | tsc 5.0 s | ...` for the final line. */
export const timings = (results) => results.map((r) => `${r.g.id} ${r.s.toFixed(1)} s`).join(" | ");
