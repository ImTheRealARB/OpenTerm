/**
 * Live script alerts (Phase 25): runs the scripts behind `ALRT AAPL SCRIPT=NAME [COND="title"]` in THIS browser, on live ticks.
 * It RUNS WHILE OPENTERM IS OPEN: the server only stores the alert list (`/api/scripts/alerts`); nothing checks them with the
 * tab closed (server-side script alerts are part 2).
 *
 * Loaded with `import()` by `liveAlertSync.ts` and only when at least one script alert exists, so it (and the script engine it
 * pulls in) never touches the startup bundle.
 *
 * For each alert, once: fetch the script text, compile it, fetch about a year of DAILY bars (and the series its `request(...)`
 * calls name), run the script over them. Firing is NEVER done for what is already true in that history: the alert / condition
 * state of the newest bar at start is remembered and skipped. Then the symbol's live ticks (the shared socket subscription
 * price alerts use too) move the newest bar (`liveBar.ts` `applyFold`): at most 4 runs a second per alert, the prices that
 * arrive in between folded into one bar update, so a quick spike still counts in the bar's high / low.
 * A run error stops that alert and is shown (status line and the ALRT list), never swallowed.
 */
import { browserFires } from "../command/alertArgs";
import { engineState, fireScriptAlert } from "../command/alerts";
import { fail, info } from "../command/status";
import { ApiError } from "../net/core";
import { errMessage } from "../net/errText";
import { marketApi } from "../net/marketApi";
import { scriptsApi, type ScriptAlert } from "../net/scriptsApi";
import { subscribe } from "../net/socket";
import { symId } from "../state/symbols";
import { onRawTicks, type RawTicks } from "../state/ticks";
import { compile, type BarCols, type Program, type RunState } from "./index";
import { refreshScriptAlerts } from "./liveAlertSync";
import { RUNS_WHILE_OPEN, scriptAlertRuns, scriptAlertText, setRun } from "./liveAlertState";
import {
  addPrice, applyFold, compileErrorText, findCondition, foldOf, messagesToFire, noConditionText, requestRange, runErrorText, seedKey, toCols,
  type Fold, type LastBar,
} from "./liveBar";

/** Minimum gap between two runs of one alert (ms). */
const MIN_RUN_GAP_MS = 250;

interface Runner {
  alert: ScriptAlert;
  /** Taken out of the list: every later step must stop. */
  removed: boolean;
  /** A SETUP step is in flight (fetching or compiling): do not start another. */
  busy: boolean;
  /** A run error stopped it for good (until the page reloads); a setup failure is retried when the list refreshes. */
  fatal: boolean;
  live: boolean;
  program: Program | null;
  rs: RunState | null;
  /** The condition title as the script spells it (null = the script's own alert() calls). */
  cond: string | null;
  last: LastBar | null;
  /** `barTime|message` pairs that were already true when the run started: never fired. */
  seeded: Set<string>;
  fold: Fold | null;
  synthetic: boolean;
  lastRunAt: number;
  timer: ReturnType<typeof setTimeout> | null;
  unsub: (() => void) | null;
  /** The last error text said on the status line, so a setup that keeps failing is not repeated every minute. */
  lastError: string | null;
}

const runners = new Map<number, Runner>();
/** symbol id -> the live runners watching it, rebuilt whenever a runner goes live or stops. */
let byId = new Map<number, Runner[]>();
let unlisten: (() => void) | null = null;

function reindex(): void {
  const m = new Map<number, Runner[]>();
  for (const r of runners.values()) {
    if (!r.live) continue;
    const id = symId(r.alert.symbol);
    m.set(id, [...(m.get(id) ?? []), r]);
  }
  byId = m;
  if (m.size && !unlisten) unlisten = onRawTicks(onTicks);
  if (!m.size && unlisten) {
    unlisten();
    unlisten = null;
  }
}

function stop(r: Runner): void {
  r.live = false;
  if (r.timer) clearTimeout(r.timer);
  r.timer = null;
  r.fold = null;
  r.unsub?.();
  r.unsub = null;
}

/** Stop an alert and show why (status line once per distinct text, and the ALRT list always). `fatal` = a run error: no retry. */
function stopWithError(r: Runner, message: string, fatal: boolean): void {
  stop(r);
  r.fatal = fatal;
  reindex();
  setRun(r.alert.id, { state: "error", error: message });
  if (r.lastError !== message) {
    r.lastError = message;
    fail(`SCRIPT ALERT ${scriptAlertText(r.alert)} STOPPED: ${message}`);
  }
}

/** Make `list` the set of running alerts: stop removed ones, start new ones, retry ones whose setup failed. */
export function syncRunners(list: ScriptAlert[]): void {
  const ids = new Set(list.map((a) => a.id));
  for (const [id, r] of runners) {
    if (ids.has(id)) continue;
    r.removed = true;
    stop(r);
    runners.delete(id);
    scriptAlertRuns.set((cur) => {
      const rest = { ...cur };
      delete rest[id];
      return rest;
    });
  }
  for (const a of list) {
    const have = runners.get(a.id);
    if (have && (have.live || have.busy || have.fatal)) continue;
    // new, or a setup that failed earlier (the script may be fixed, the network back): start it
    const r: Runner = have ?? {
      alert: a, removed: false, busy: false, fatal: false, live: false, program: null, rs: null, cond: a.cond, last: null,
      seeded: new Set(), fold: null, synthetic: false, lastRunAt: 0, timer: null, unsub: null, lastError: null,
    };
    runners.set(a.id, r);
    void setup(r);
  }
  reindex();
}

/** The history call for one series. A failure is shown by the caller as the alert's error. */
async function dailyCols(symbol: string, range: string, interval: string): Promise<BarCols> {
  const env = await marketApi.history(symbol, range, interval, true);
  const cols = toCols(env.data);
  if (!cols) throw new Error(`NO ${interval.toUpperCase()} BARS FOR ${symbol}`);
  return cols;
}

async function setup(r: Runner): Promise<void> {
  const a = r.alert;
  r.busy = true;
  setRun(a.id, { state: "loading", error: undefined });
  const bad = (msg: string): void => {
    r.busy = false;
    if (!r.removed) stopWithError(r, msg, false);
  };
  try {
    let source: string;
    try {
      source = (await scriptsApi.get(a.script)).source;
    } catch (e) {
      return bad(e instanceof ApiError && e.status === 404 ? `SCRIPT NOT FOUND: ${a.script}` : `SCRIPT ${a.script}: ${errMessage(e)}`);
    }
    const c = compile(source);
    if (!c.ok) return bad(compileErrorText(a.script, c.errors[0]));
    const program = c.program;
    let cond: string | null = null;
    if (a.cond !== null) {
      cond = findCondition(program.meta.conditions, a.cond);
      if (cond === null) return bad(noConditionText(a.cond, a.script, program.meta.conditions));
    }
    const requests: Record<string, BarCols> = {};
    for (const q of program.resolveRequests()) {
      if (q.symbol === "") continue; // the script's own symbol at a longer timeframe: the engine builds it from the bars
      const want = requestRange(q.timeframe);
      if (!want) return bad(`REQUEST TIMEFRAME ${q.timeframe.toUpperCase()} IS NOT AVAILABLE IN LIVE ALERTS (1D, 1W, 1M)`);
      requests[`${q.symbol}|${q.timeframe}`] = await dailyCols(q.symbol, want.range, want.interval);
    }
    const bars = await dailyCols(a.symbol, "1Y", "1d");
    if (r.removed) {
      r.busy = false;
      return;
    }

    const rs = program.run(bars, { requests, chartTimeframe: "1D" });
    const first = rs.tick();
    if (first.error) return bad(runErrorText(first.error));
    const n = first.n;
    const last: LastBar = { t: bars.t![n - 1], o: bars.o[n - 1], h: bars.h[n - 1], l: bars.l[n - 1], c: bars.c[n - 1], v: bars.v[n - 1] };
    // Whatever is already true on the newest bar now is history, not news: remember it so it is never fired.
    r.seeded = new Set(messagesToFire(first, program.meta.conditions, cond).map((m) => seedKey(last.t, m)));
    Object.assign(r, { program, rs, cond, last, fold: null, synthetic: a.symbol.startsWith("SYN") });
    r.unsub = subscribe([a.symbol]);
    r.live = true;
    r.busy = false;
    r.lastError = null;
    setRun(a.id, { state: "running", error: undefined });
    reindex();
  } catch (e) {
    bad(errMessage(e)); // a failed history fetch, or anything unexpected: shown, and retried when the list refreshes
  }
}

/** Every raw tick of the app: fold the prices of watched symbols into their alert's pending bar update. */
function onTicks(t: RawTicks): void {
  const fixtures = engineState.get()?.fixtures;
  for (let i = 0; i < t.n; i++) {
    const watching = byId.get(t.id[i]);
    if (!watching) continue;
    const price = t.price[i];
    if (!Number.isFinite(price)) continue;
    const testData = browserFires(t.src[i], fixtures); // SYNTHETIC ticks and fixture mode are labelled test data, never passed off as real
    for (const r of watching) {
      r.fold = r.fold ? addPrice(r.fold, price) : foldOf(price);
      if (testData) r.synthetic = true;
      schedule(r);
    }
  }
}

function schedule(r: Runner): void {
  if (r.timer) return;
  const wait = Math.max(0, r.lastRunAt + MIN_RUN_GAP_MS - Date.now());
  r.timer = setTimeout(() => {
    r.timer = null;
    runOnce(r);
  }, wait);
}

function runOnce(r: Runner): void {
  const f = r.fold;
  r.fold = null;
  if (!f || !r.live || !r.rs || !r.program || !r.last) return;
  r.lastRunAt = Date.now();
  const nowSec = r.lastRunAt / 1000;
  const { append, bar } = applyFold(r.last, f, nowSec);
  if (append) r.rs.append(bar);
  else r.rs.updateLast(bar);
  r.last = bar;
  const tick = r.rs.tick();
  if (tick.error) return stopWithError(r, runErrorText(tick.error), true);
  for (const message of messagesToFire(tick, r.program.meta.conditions, r.cond)) {
    if (r.seeded.has(seedKey(bar.t, message))) continue;
    // fireScriptAlert dedupes once per bar per message, so a repeat run of the same bar stays quiet
    if (fireScriptAlert({ symbol: r.alert.symbol, script: r.alert.script, message, barTime: bar.t, synthetic: r.synthetic })) {
      setRun(r.alert.id, { firedAt: nowSec, message });
    }
  }
}

/**
 * `ALRT AAPL SCRIPT=NAME [COND="title"]`: check the script and condition NOW (so a typo fails at the command line, not later),
 * save the alert on the server, then let the runner pick it up. Every failure is said on the status line.
 */
export async function createScriptAlert(spec: { symbol: string; script: string; cond: string | null }): Promise<boolean> {
  let source: string;
  try {
    source = (await scriptsApi.get(spec.script)).source;
  } catch (e) {
    return fail(e instanceof ApiError && e.status === 404 ? `SCRIPT NOT FOUND: ${spec.script}` : `SCRIPT ${spec.script}: ${errMessage(e)}`);
  }
  const c = compile(source);
  if (!c.ok) return fail(compileErrorText(spec.script, c.errors[0]));
  let cond = spec.cond;
  if (cond !== null) {
    const title = findCondition(c.program.meta.conditions, cond);
    if (title === null) return fail(noConditionText(cond, spec.script, c.program.meta.conditions));
    cond = title;
  }
  let saved: ScriptAlert;
  try {
    saved = await scriptsApi.addAlert({ symbol: spec.symbol, script: spec.script, cond });
  } catch (e) {
    return fail(`SCRIPT ALERT NOT SAVED: ${errMessage(e)}`);
  }
  info(`SCRIPT ALERT SC${saved.id} SET: ${scriptAlertText(saved)} (${RUNS_WHILE_OPEN})`);
  await refreshScriptAlerts();
  return true;
}
