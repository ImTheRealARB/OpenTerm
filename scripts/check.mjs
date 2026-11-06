// Changed-files check: runs only the tests a change can affect, plus tsc and ruff. The planner behind check.ps1 / check.sh.
//   node scripts/check.mjs [--base=main] [--all] [--dry-run] [--no-e2e] [--files=a,b]
//   --base=REF    compare against the merge-base of REF and HEAD, plus the working tree and untracked files (default main)
//   --all         ignore the diff: ruff ., tsc, all of pytest, vitest, Playwright (what gates.mjs runs, in the same stages)
//   --dry-run     print the plan, run nothing
//   --no-e2e      leave Playwright out
//   --files=a,b   plan for these repo-relative paths instead of the git diff (used to test the planner)
// How a change maps to tests (a heuristic, so `--all` / gates.mjs stay the pre-merge truth):
//   backend: import graph of backend/openterm (relative and absolute imports). A test runs when it imports a changed module or any
//     module that depends on one; a test whose name contains a changed module's name runs too; a change that reaches openterm.main
//     adds test_app.py + test_api.py; registry/keybindings changes add test_functions_doc.py.
//   frontend: import graph of frontend/src and e2e (type-only imports ignored). vitest runs the *.test.ts files that depend on a change.
//     Playwright runs a spec when it was changed, imports a changed helper, or names a function code (CENB ...) whose panel the change
//     reaches; a change that reaches the app shell (App.tsx, main.tsx) runs every spec. Backend-only changes skip Playwright (mocked).
//   config files (pyproject, lockfiles, tsconfig, vite config, conftest) run everything of that side.
// Stages: ruff + tsc + eslint side by side and fail fast; then pytest + vitest side by side; then Playwright (needs ports 4173 and 8000 free).
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join, posix, relative } from "node:path";
import { busyPorts, failureTail, npx, refused, root, run, summaryLine, timings } from "./lib/proc.mjs";

const argv = process.argv.slice(2);
const flag = (n) => argv.includes(`--${n}`);
const opt = (n) => argv.find((a) => a.startsWith(`--${n}=`))?.slice(n.length + 3);
const ALL = flag("all");
const base = opt("base") ?? "main";

// ---------- file inventory ----------
const SKIP_DIRS = new Set(["node_modules", ".venv", "__pycache__", "dist", ".git", "test-results", "playwright-report", ".pytest_cache", ".ruff_cache"]);
function walk(dir, exts, out = []) {
  const abs = join(root, dir);
  if (!existsSync(abs)) return out;
  for (const e of readdirSync(abs, { withFileTypes: true })) {
    if (e.isDirectory()) {
      if (!SKIP_DIRS.has(e.name)) walk(`${dir}/${e.name}`, exts, out);
    } else if (exts.some((x) => e.name.endsWith(x))) out.push(`${dir}/${e.name}`);
  }
  return out;
}
const read = (f) => readFileSync(join(root, f), "utf8");
const strip = (f) => f.replace(/\.(tsx?|css)$/, "");

// ---------- changed files ----------
function changedFiles() {
  const explicit = opt("files");
  if (explicit) return explicit.split(",").map((s) => s.trim().replaceAll("\\", "/")).filter(Boolean);
  const git = (a) => execFileSync("git", a, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  let mb = base;
  try {
    mb = git(["merge-base", base, "HEAD"]).trim();
  } catch {
    // base is not a ref we can resolve: diff against it as given
  }
  const tracked = git(["diff", "--name-only", mb]).split("\n");
  const untracked = git(["ls-files", "--others", "--exclude-standard"]).split("\n");
  return [...new Set([...tracked, ...untracked].map((s) => s.trim()).filter(Boolean))];
}

// ---------- backend graph ----------
const pyFiles = walk("backend/openterm", [".py"]);
const modOf = (f) => {
  const p = f.slice("backend/".length, -3).split("/");
  if (p[p.length - 1] === "__init__") p.pop();
  return p.join(".");
};
const fileOfMod = new Map(pyFiles.map((f) => [modOf(f), f]));
const modSet = new Set(fileOfMod.keys());

/** URL stems a route module serves: `router = APIRouter(prefix="/api/world")` + `@router.get("/geo/{kind}")` -> "/api/world/geo/".
 *  Stems no longer than "/api/" are dropped: they would match every route test. */
function routeStems(text) {
  const prefix = new Map();
  for (const m of text.matchAll(/^(\w+)\s*=\s*APIRouter\(([^)]*)\)/gm)) prefix.set(m[1], /prefix\s*=\s*"([^"]*)"/.exec(m[2])?.[1] ?? "");
  const out = new Set();
  for (const m of text.matchAll(/^@(\w+)\.(?:get|post|put|patch|delete|websocket|api_route)\(\s*"([^"]*)"/gm)) {
    if (!prefix.has(m[1])) continue;
    const stem = (prefix.get(m[1]) + m[2]).split("{")[0];
    if (stem.length > "/api/".length) out.add(stem);
  }
  return out;
}

function pyImports(text, self, isPkg) {
  const code = text.replace(/#.*$/gm, "");
  const pkg = isPkg ? self : self.split(".").slice(0, -1).join(".");
  const found = new Set();
  const add = (m) => modSet.has(m) && found.add(m);
  for (const m of code.matchAll(/^[ \t]*from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^\n]+)/gm)) {
    const dots = m[1].length;
    let target = m[2];
    if (dots) {
      const parts = pkg.split(".");
      const up = parts.slice(0, Math.max(parts.length - (dots - 1), 0)).join(".");
      target = m[2] ? `${up}.${m[2]}` : up;
    }
    if (!dots && !target.startsWith("openterm")) continue;
    add(target);
    for (const n of m[3].replace(/[()\\]/g, " ").split(",")) {
      const name = n.trim().split(/\s+as\s+/)[0].trim();
      if (name && name !== "*") add(`${target}.${name}`);
    }
  }
  for (const m of code.matchAll(/^[ \t]*import[ \t]+(openterm[\w.]*)/gm)) add(m[1]);
  return found;
}

function backendPlan(changed, allBackend) {
  const tests = walk("backend/tests", [".py"]).filter((f) => basename(f).startsWith("test_"));
  const plan = { tests: new Set(), ruff: [], notes: [], total: tests.length, all: false };
  const src = changed.filter((f) => f.startsWith("backend/openterm/") && f.endsWith(".py"));
  plan.ruff = changed.filter((f) => f.startsWith("backend/") && f.endsWith(".py") && existsSync(join(root, f))).map((f) => f.slice("backend/".length));
  const everything =
    allBackend ||
    changed.some((f) => ["backend/pyproject.toml", "backend/uv.lock", "backend/tests/conftest.py", "backend/openterm/__init__.py"].includes(f));
  if (everything) {
    plan.all = true;
    plan.tests = new Set(tests);
    return plan;
  }
  // dependents graph: module -> modules that import it (and children depend on their package)
  const dependents = new Map();
  const edge = (from, to) => {
    if (!dependents.has(to)) dependents.set(to, new Set());
    dependents.get(to).add(from);
  };
  for (const f of pyFiles) {
    const self = modOf(f);
    for (const d of pyImports(read(f), self, f.endsWith("__init__.py"))) edge(self, d);
    const parts = self.split(".");
    for (let i = 2; i < parts.length; i++) edge(self, parts.slice(0, i).join(".")); // importing a.b runs a/__init__ (not the bare root package)
  }
  const affected = new Set(src.map(modOf).filter((m) => modSet.has(m)));
  let reachesMain = src.some((f) => modOf(f) === "openterm.main");
  for (const q = [...affected]; q.length; ) {
    for (const d of dependents.get(q.pop()) ?? []) {
      if (d === "openterm.main") reachesMain = true; // main imports every route and provider: do not pull in every test that builds the app
      else if (!affected.has(d)) (affected.add(d), q.push(d));
    }
  }
  const leaves = [...new Set(src.map((f) => basename(f, ".py")).filter((l) => l.length >= 4 && l !== "__init__"))];
  for (const t of tests) {
    if (changed.includes(t)) plan.tests.add(t);
    const stem = basename(t, ".py");
    if (leaves.some((l) => stem.includes(l))) plan.tests.add(t);
    for (const d of pyImports(read(t), "tests." + stem, false)) if (affected.has(d)) plan.tests.add(t);
  }
  // Route tests reach their routes over HTTP (the `client` fixture), never by importing the route module, and the import walk
  // stops at openterm.main, so a route change used to select no route test at all (audit G-1). For every affected module that
  // declares routes, add each test whose text names one of its paths (router prefix + decorator path, cut at the first "{").
  const routeCovered = new Set(); // affected route modules with at least one test naming their paths
  for (const m of affected) {
    const f = fileOfMod.get(m);
    if (!f) continue;
    for (const stem of routeStems(read(f))) {
      for (const t of tests) {
        if (read(t).includes(stem)) (plan.tests.add(t), routeCovered.add(f));
      }
    }
  }
  const want = (name) => tests.find((t) => basename(t) === name);
  const addNamed = (...names) => names.map(want).filter(Boolean).forEach((t) => plan.tests.add(t));
  if (reachesMain) addNamed("test_app.py", "test_api.py");
  if (changed.some((f) => /^(frontend\/src\/functions\/registry\.ts|frontend\/src\/keys\/(keybindings\.json|keys\.ts)|scripts\/gen_functions_doc\.py|docs\/FUNCTIONS\.md)$/.test(f))) {
    addNamed("test_functions_doc.py");
  }
  const fixtures = changed.filter((f) => f.startsWith("backend/tests/fixtures/"));
  for (const fx of fixtures) {
    const stem = basename(fx).replace(/\.[^.]+$/, "");
    const hit = tests.filter((t) => read(t).includes(stem));
    if (hit.length) hit.forEach((t) => plan.tests.add(t));
    else addNamed("test_adapters.py", "test_api.py");
  }
  const untested = src.filter((f) => {
    if (routeCovered.has(f)) return false;
    const m = modOf(f);
    const stem = basename(f, ".py");
    return ![...plan.tests].some((t) => basename(t, ".py").includes(stem) || pyImports(read(t), "tests." + basename(t, ".py"), false).has(m));
  });
  if (untested.length) plan.notes.push(`no test imports or is named after: ${untested.join(", ")} (smoke tests only; consider adding one)`);
  return plan;
}

// ---------- frontend graph ----------
const feFiles = [...walk("frontend/src", [".ts", ".tsx", ".css"]), ...walk("frontend/e2e", [".ts"])];
const feSet = new Set(feFiles);
function resolveImport(from, spec) {
  const p = posix.normalize(posix.join(posix.dirname(from), spec));
  for (const c of [p, `${p}.ts`, `${p}.tsx`, `${p}/index.ts`, `${p}/index.tsx`, p.replace(/\.js$/, ".ts"), p.replace(/\.js$/, ".tsx")]) if (feSet.has(c)) return c;
  return null;
}
function feImports(f) {
  const text = read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const out = new Set();
  const add = (spec) => {
    if (!spec.startsWith(".")) return;
    const r = resolveImport(f, spec);
    if (r) out.add(r);
  };
  // `import type ... from` and `export type ... from` are erased: no runtime dependency
  for (const m of text.matchAll(/^\s*(?:import|export)\s+(type\s+)?[^;'"]*?from\s*["']([^"']+)["']/gm)) if (!m[1]) add(m[2]);
  for (const m of text.matchAll(/^\s*import\s*["']([^"']+)["']/gm)) add(m[1]);
  for (const m of text.matchAll(/\bimport\(\s*["']([^"']+)["']\s*\)/g)) add(m[1]);
  return out;
}

function frontendPlan(changed, allFront) {
  const plan = { vitest: new Set(), e2e: new Set(), tsc: false, notes: [], total: { vitest: 0, e2e: 0 }, allE2e: false };
  const tests = feFiles.filter((f) => /\.test\.tsx?$/.test(f));
  const specs = feFiles.filter((f) => f.endsWith(".spec.ts"));
  plan.total = { vitest: tests.length, e2e: specs.length };
  const fe = changed.filter((f) => f.startsWith("frontend/") && !f.startsWith("frontend/node_modules/"));
  plan.tsc = allFront || fe.some((f) => /\.(tsx?|json)$/.test(f) || /^frontend\/(index\.html|vite\.config\.ts|playwright\.config\.ts)$/.test(f));
  const configChange = fe.some((f) => /^frontend\/(package\.json|package-lock\.json|tsconfig[^/]*\.json|vite\.config\.ts)$/.test(f));
  if (allFront || configChange) {
    tests.forEach((t) => plan.vitest.add(t));
    specs.forEach((t) => plan.e2e.add(t));
    plan.allE2e = true;
    return plan;
  }
  const seeds = fe.filter((f) => feSet.has(f) || f.startsWith("frontend/src/") || f.startsWith("frontend/e2e/"));
  if (fe.includes("frontend/index.html") || fe.includes("frontend/playwright.config.ts")) plan.allE2e = true;
  // reverse closure over runtime imports; registry.ts's lazy imports are skipped so one panel does not pull in every other panel
  const dependents = new Map();
  for (const f of feFiles) {
    for (const d of feImports(f)) {
      if (f === "frontend/src/functions/registry.ts") continue;
      if (!dependents.has(d)) dependents.set(d, new Set());
      dependents.get(d).add(f);
    }
  }
  const affected = new Set(seeds.filter((f) => feSet.has(f)));
  for (const q = [...affected]; q.length; ) {
    for (const d of dependents.get(q.pop()) ?? []) if (!affected.has(d)) (affected.add(d), q.push(d));
  }
  for (const t of tests) if (affected.has(t) || changed.includes(t)) plan.vitest.add(t);
  // registry/keybinding edits change HELP and the shortcut list: the registry's own dependents are in `affected` already
  const shell = ["frontend/src/App.tsx", "frontend/src/main.tsx"].some((f) => affected.has(f));
  const codes = new Set(
    [...affected].filter((f) => f.startsWith("frontend/src/functions/")).map((f) => basename(f).replace(/\.(tsx?)$/, "")).filter((c) => /^[A-Z][A-Z0-9]*$/.test(c)),
  );
  const changedRegistry = fe.includes("frontend/src/functions/registry.ts");
  if (shell || plan.allE2e) {
    specs.forEach((s) => plan.e2e.add(s));
    plan.allE2e = true;
  } else {
    for (const s of specs) {
      if (affected.has(s)) plan.e2e.add(s);
      else if (codes.size) {
        const text = read(s);
        if ([...codes].some((c) => new RegExp(`\\b${c}\\b`).test(text))) plan.e2e.add(s);
      }
    }
    if (changedRegistry && !plan.e2e.size) plan.notes.push("registry.ts changed: panel entries are not browser-tested one by one; use --all before merging");
  }
  return plan;
}

// ---------- assemble ----------
const changed = ALL ? [] : changedFiles();
const be = backendPlan(changed, ALL);
const fe = frontendPlan(changed, ALL);
const noE2e = flag("no-e2e");
const touchedBackend = ALL || changed.some((f) => f.startsWith("backend/"));
const touchedFrontend = ALL || changed.some((f) => f.startsWith("frontend/"));
const rel = (list, dir) => [...list].sort().map((f) => relative(dir, f).replaceAll("\\", "/"));

const gates = { stage1: [], stage2: [], stage3: [] };
if (ALL) gates.stage1.push({ id: "ruff", cwd: "backend", cmd: "uv", args: ["run", "ruff", "check", "."] });
else if (be.ruff.length) gates.stage1.push({ id: "ruff", cwd: "backend", cmd: "uv", args: ["run", "ruff", "check", ...be.ruff] });
if (fe.tsc) gates.stage1.push({ id: "tsc", cwd: "frontend", cmd: npx, args: ["tsc", "--noEmit"] });
// React hooks lint (audit G-2) on the changed frontend sources only; everything when --all
const lintFiles = changed.filter((f) => /^frontend\/src\/.*\.tsx?$/.test(f) && existsSync(join(root, f))).map((f) => f.slice("frontend/".length));
if (ALL) gates.stage1.push({ id: "eslint", cwd: "frontend", cmd: npx, args: ["eslint", "."] });
else if (lintFiles.length) gates.stage1.push({ id: "eslint", cwd: "frontend", cmd: npx, args: ["eslint", ...lintFiles] });
if (be.tests.size) {
  const files = be.all ? [] : rel(be.tests, "backend");
  gates.stage2.push({ id: "pytest", cwd: "backend", cmd: "uv", args: ["run", "pytest", "-q", ...(files.length && files.length <= 2 ? ["-n", "0"] : []), ...files] });
}
if (fe.vitest.size) {
  const files = fe.vitest.size === fe.total.vitest ? [] : rel(fe.vitest, "frontend");
  gates.stage2.push({ id: "vitest", cwd: "frontend", cmd: npx, args: ["vitest", "run", ...files] });
}
if (fe.e2e.size && !noE2e && (ALL || touchedFrontend)) {
  const files = fe.e2e.size === fe.total.e2e ? [] : rel(fe.e2e, "frontend");
  gates.stage3.push({ id: "e2e", cwd: "frontend", cmd: npx, args: ["playwright", "test", ...files], env: { CI: "1" }, ports: [4173, 8000] });
}

// ---------- print the plan ----------
const list = (items, n = 6) => (items.length > n ? `${items.slice(0, n).join(" ")} ... (+${items.length - n})` : items.join(" "));
console.log(ALL ? "mode: --all (everything, like gates.mjs)" : `base: ${base}; ${changed.length} changed file(s): ${list(changed, 8) || "none"}`);
console.log(`ruff   : ${gates.stage1.find((g) => g.id === "ruff") ? (ALL ? "backend (all)" : list(be.ruff)) : "skip (no backend .py changed)"}`);
console.log(`tsc    : ${fe.tsc ? "yes" : "skip (no frontend source changed)"}`);
console.log(`pytest : ${be.tests.size ? `${be.tests.size} of ${be.total} file(s): ${be.all ? "all" : list(rel(be.tests, "backend/tests"))}` : touchedBackend ? "none selected" : "skip (no backend change)"}`);
console.log(`vitest : ${fe.vitest.size ? `${fe.vitest.size} of ${fe.total.vitest} file(s): ${fe.vitest.size === fe.total.vitest ? "all" : list(rel(fe.vitest, "frontend/src"))}` : touchedFrontend ? "none selected" : "skip (no frontend change)"}`);
console.log(`e2e    : ${noE2e ? "skip (--no-e2e)" : gates.stage3.length ? `${fe.e2e.size} of ${fe.total.e2e} spec(s): ${fe.e2e.size === fe.total.e2e ? "all" : list(rel(fe.e2e, "frontend/e2e"))}` : "skip (no frontend change reaches a browser spec)"}`);
for (const n of [...be.notes, ...fe.notes]) console.log(`note   : ${n}`);
if (!gates.stage1.length && !gates.stage2.length && !gates.stage3.length) {
  console.log("nothing to run");
  process.exit(0);
}
if (flag("dry-run")) {
  for (const [name, gs] of Object.entries(gates)) for (const g of gs) console.log(`${name}: (cd ${g.cwd}) ${g.cmd.replace(/\.cmd$/, "")} ${g.args.join(" ")}`);
  process.exit(0);
}

// ---------- run ----------
const t0 = Date.now();
const results = [];
const go = async (gs) => {
  const rs = await Promise.all(
    gs.map(async (g) => {
      const why = g.ports ? await busyPorts(g.ports) : "";
      return why ? refused(g, why) : run(g);
    }),
  );
  results.push(...rs);
  return rs.every((r) => r.code === 0);
};
let ok = await go(gates.stage1);
if (ok) ok = await go(gates.stage2);
if (ok) await go(gates.stage3);
for (const r of results) console.log(summaryLine(r));
const failed = results.filter((r) => r.code !== 0);
if (failed.length) for (const r of failed) console.log(failureTail(r));
const notRun = [...gates.stage2, ...gates.stage3].filter((g) => !results.some((r) => r.g === g)).map((g) => g.id);
if (notRun.length) console.log(`not run (an earlier stage failed): ${notRun.join(", ")}`);
console.log(`\n${failed.length ? "CHECK FAILED" : "CHECK PASS"} in ${((Date.now() - t0) / 1000).toFixed(1)} s  (${timings(results)})`);
process.exit(failed.length ? 1 : 0);
