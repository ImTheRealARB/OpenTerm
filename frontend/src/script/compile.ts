/**
 * OpenTerm Script compiler: syntax tree -> a tree of JavaScript closures ("closure compilation").
 *
 * Every expression becomes a small function `() => value`, every statement a function `() => code`. Running one bar is
 * calling the top function once. There is no `eval` and no `new Function`: the closures are made by ordinary code below,
 * so a script can only do what this file lets it do.
 *
 *   Ev  = () => unknown      an expression: its value on the current bar (`ctx.bar`)
 *   St  = () => number       a statement: 0 = carry on, 1 = `break`, 2 = `continue`
 *
 * Variables live in numbered SLOTS (`ctx.slots[i]`), resolved once here. A user function is compiled again at every call
 * site, so each call site has its own slots and its own `ta.*` states (spec 1.3).
 *
 * The checker (checker.ts) has already rejected bad scripts; this file trusts it and only guards what the checker
 * cannot know (the values at run time).
 */
import type { Ast, Expr, Pos, Stmt } from "./ast";
import { defaultValue, matchArgs, type ParamLike } from "./args";
import { FN, MATH1, methodImpl, methodNs, textOf } from "./builtins";
import type { Checked, InputDef } from "./checker";
import { Ctx, type LibSite, type OutRec, type ReqSite } from "./ctx";
import { BY_NAME, COLORS, LIMITS, TIMEFRAMES } from "./names";
import { makeTa, type TaFn, type TaHint } from "./ta";
import { PlotH, ScriptRuntimeError, colorOrNull, truth, typeName } from "./values";
import { findIndicator } from "../chart/library/catalog";

type Ev = () => unknown;
type St = () => number;

// ---------------------------------------------------------------- scopes (compile time)

type VarKind = "var" | "input" | "src" | "param" | "loop";
interface VarB {
  kind: VarKind;
  /** Slot number (not used by input / src: those are constants or bar series). */
  slot: number;
  /** input: its value. */
  val?: unknown;
  /** src: the bar series it reads ("close", "hl2" ...). */
  src?: string;
  /** The value is a true / false (decides how `plotshape(absolute)` and `str.tostring` treat it). */
  bool?: boolean;
}
class BScope {
  vars = new Map<string, VarB>();
  constructor(public parent: BScope | null) {}
  lookup(name: string): VarB | undefined {
    for (let s: BScope | null = this; s; s = s.parent) {
      const v = s.vars.get(name);
      if (v) return v;
    }
    return undefined;
  }
}
interface FuncB {
  def: Extract<Stmt, { t: "func" }>;
  /** The global variables that existed when the function was defined (it can read these). */
  globals: Map<string, VarB>;
}

// ---------------------------------------------------------------- run-time helpers

function rt(msg: string, pos: Pos): never {
  throw new ScriptRuntimeError(msg, pos);
}
/** Give an error from a built-in the line and column of the call that failed. */
function withPos(e: unknown, pos: Pos): never {
  if (e instanceof ScriptRuntimeError && !e.pos) e.pos = pos;
  throw e;
}
function stepFail(c: Ctx, pos: Pos): never {
  c.sb = 0;
  throw new ScriptRuntimeError("STEP LIMIT", pos);
}
function addSlow(a: unknown, b: unknown, pos: Pos): unknown {
  if (typeof a === "string" && typeof b === "string") return a + b;
  return rt(`CANNOT ADD ${typeName(a)} AND ${typeName(b)} (USE STR.TOSTRING)`, pos);
}
function numErr(op: string, a: unknown, b: unknown, pos: Pos): never {
  return rt(`CANNOT USE ${op} ON ${typeName(a)} AND ${typeName(b)}`, pos);
}
function cmpSlow(op: string, a: unknown, b: unknown, pos: Pos): number {
  if (typeof a === "string" && typeof b === "string") {
    return (op === "<" ? a < b : op === "<=" ? a <= b : op === ">" ? a > b : a >= b) ? 1 : 0;
  }
  return numErr(op, a, b, pos);
}
const NUM_FN = (v: unknown, pos: Pos): number => (typeof v === "number" ? v : rt(`EXPECTED A NUMBER, GOT ${typeName(v)}`, pos));

/** A history offset: NaN stays NaN (na), otherwise a whole number 0..5000. */
function lookback(raw: unknown, pos: Pos): number {
  if (typeof raw !== "number") return rt(`HISTORY OFFSET MUST BE A NUMBER, GOT ${typeName(raw)}`, pos);
  if (raw !== raw) return NaN;
  const k = Math.floor(raw);
  if (k < 0) return rt("HISTORY OFFSET CANNOT BE NEGATIVE", pos);
  if (k > LIMITS.lookback) return rt(`LOOKBACK TOO LARGE (MAX ${LIMITS.lookback})`, pos);
  return k;
}

const SERIES_NAMES = new Set(["open", "high", "low", "close", "volume", "time", "hl2", "hlc3", "ohlc4", "bar_index", "last_bar_index"]);

/** The value of a bar series at bar index i. */
function seriesAt(c: Ctx, name: string): (i: number) => number {
  switch (name) {
    case "open":
      return (i) => c.o[i];
    case "high":
      return (i) => c.h[i];
    case "low":
      return (i) => c.l[i];
    case "close":
      return (i) => c.c[i];
    case "volume":
      return (i) => c.v[i];
    case "time":
      return (i) => c.t[i];
    case "hl2":
      return (i) => (c.h[i] + c.l[i]) / 2;
    case "hlc3":
      return (i) => (c.h[i] + c.l[i] + c.c[i]) / 3;
    case "ohlc4":
      return (i) => (c.o[i] + c.h[i] + c.c[i] + c.l[i]) / 4;
    case "bar_index":
      return (i) => i;
    case "last_bar_index":
      return () => c.n - 1;
    default:
      throw new Error(`no series ${name}`);
  }
}

const TA_LEN_PARAM: Record<string, number> = {
  sma: 1, ema: 1, wma: 1, rma: 1, vwma: 1, rsi: 1, stdev: 1, variance: 1, highest: 1, lowest: 1,
  change: 1, mom: 1, roc: 1, atr: 0, rising: 1, falling: 1, linreg: 1, bb: 1, stoch: 3,
};

const OUTPUT_NAMES = new Set(["plot", "hline", "fill", "bgcolor", "plotshape", "alert", "alertcondition", "indicator"]);

// ---------------------------------------------------------------- the builder

export class Builder {
  scope = new BScope(null);
  private funcs = new Map<string, FuncB>();

  constructor(
    private c: Ctx,
    private checked: Checked,
    private inputs: Map<string, unknown>,
  ) {}

  // ---------------------------------------------------------------- whole program

  /** Compile the top-level statements into one function that runs a whole bar. */
  program(ast: Ast): St {
    this.c.maxLabels = this.checked.meta.maxLabels;
    const body = ast.body.map((s) => this.stmt(s));
    return this.seq(body);
  }

  private newSlot(isVar: boolean): number {
    const c = this.c;
    const i = c.slots.length;
    c.slots.push(NaN);
    c.histCap.push(0);
    c.hist.push(null);
    if (!isVar) c.resets.push(i);
    return i;
  }

  private seq(list: St[]): St {
    if (list.length === 0) return () => 0;
    if (list.length === 1) return list[0];
    return () => {
      for (let i = 0; i < list.length; i++) {
        const r = list[i]();
        if (r !== 0) return r;
      }
      return 0;
    };
  }

  private block(stmts: Stmt[]): St {
    const saved = this.scope;
    this.scope = new BScope(saved);
    const out = this.seq(stmts.map((s) => this.stmt(s)));
    this.scope = saved;
    return out;
  }

  // ---------------------------------------------------------------- statements

  private stmt(s: Stmt): St {
    const c = this.c;
    switch (s.t) {
      case "decl": {
        // inputs: the value is known now (settings are fixed for a run), so nothing runs per bar
        if (s.value.t === "call") {
          const def = this.checked.inputDefs.get(s.value);
          if (def) {
            const val = this.inputs.get(def.title);
            this.scope.vars.set(s.name, def.kind === "source" ? { kind: "src", slot: -1, src: String(val) } : { kind: "input", slot: -1, val });
            return () => 0;
          }
        }
        const ev = this.ex(s.value);
        const bool = this.isBoolish(s.value);
        const slot = this.newSlot(s.isVar);
        this.scope.vars.set(s.name, { kind: "var", slot, bool });
        const S = c.slots;
        const pos = s.pos;
        if (s.isVar) {
          // `var`: the right side runs the first time this line runs; later bars keep the value
          const flag = { done: 0 };
          c.states.push(flag);
          return () => {
            if (++c.sb > c.barCap) stepFail(c, pos);
            if (flag.done === 0) {
              S[slot] = ev();
              flag.done = 1;
            }
            return 0;
          };
        }
        return () => {
          if (++c.sb > c.barCap) stepFail(c, pos);
          S[slot] = ev();
          return 0;
        };
      }
      case "tdecl": {
        const ev = this.ex(s.value);
        const slots = s.names.map((n) => {
          const slot = this.newSlot(false);
          this.scope.vars.set(n, { kind: "var", slot });
          return slot;
        });
        const S = c.slots;
        const pos = s.pos;
        return () => {
          if (++c.sb > c.barCap) stepFail(c, pos);
          const r = ev();
          if (!Array.isArray(r) || r.length !== slots.length) rt(`EXPECTED ${slots.length} VALUES`, pos);
          for (let i = 0; i < slots.length; i++) S[slots[i]] = r[i];
          return 0;
        };
      }
      case "assign": {
        const v = this.scope.lookup(s.name) as VarB;
        const ev = this.ex(s.value);
        const S = c.slots;
        const slot = v.slot;
        const pos = s.pos;
        if (s.op === ":=") {
          return () => {
            if (++c.sb > c.barCap) stepFail(c, pos);
            S[slot] = ev();
            return 0;
          };
        }
        const op = s.op[0];
        return () => {
          if (++c.sb > c.barCap) stepFail(c, pos);
          const a = S[slot];
          const b = ev();
          if (typeof a === "number" && typeof b === "number") {
            S[slot] = op === "+" ? a + b : op === "-" ? a - b : op === "*" ? a * b : b === 0 ? NaN : a / b;
          } else if (op === "+") S[slot] = addSlow(a, b, pos);
          else numErr(op, a, b, pos);
          return 0;
        };
      }
      case "expr": {
        const ev = this.ex(s.e);
        const pos = s.pos;
        return () => {
          if (++c.sb > c.barCap) stepFail(c, pos);
          ev();
          return 0;
        };
      }
      case "if": {
        const cond = this.ex(s.cond);
        const then = this.block(s.then);
        const els = s.else_ ? this.block(s.else_) : null;
        const pos = s.pos;
        return () => {
          if (++c.sb > c.barCap) stepFail(c, pos);
          if (truth(cond())) return then();
          return els ? els() : 0;
        };
      }
      case "for": {
        const from = this.ex(s.from);
        const to = this.ex(s.to);
        const by = s.by ? this.ex(s.by) : null;
        const saved = this.scope;
        this.scope = new BScope(saved);
        const slot = this.newSlot(false);
        this.scope.vars.set(s.v, { kind: "loop", slot });
        const body = this.seq(s.body.map((b) => this.stmt(b)));
        this.scope = saved;
        const S = c.slots;
        const pos = s.pos;
        return () => {
          if (++c.sb > c.barCap) stepFail(c, pos);
          const a = NUM_FN(from(), pos);
          const b = NUM_FN(to(), pos);
          let step = a <= b ? 1 : -1;
          if (by) {
            step = NUM_FN(by(), pos);
            if (step === 0 || step !== step) rt("FOR STEP MUST NOT BE 0 OR NA", pos);
          }
          for (let i = a; step > 0 ? i <= b : i >= b; i += step) {
            if (++c.sb > c.barCap) stepFail(c, pos);
            S[slot] = i;
            const r = body();
            if (r === 1) break;
          }
          return 0;
        };
      }
      case "while": {
        const cond = this.ex(s.cond);
        const body = this.block(s.body);
        const pos = s.pos;
        return () => {
          while (truth(cond())) {
            if (++c.sb > c.barCap) stepFail(c, pos);
            const r = body();
            if (r === 1) break;
          }
          return 0;
        };
      }
      case "break":
        return () => {
          return 1;
        };
      case "continue":
        return () => {
          return 2;
        };
      case "func": {
        this.funcs.set(s.name, { def: s, globals: new Map(this.scope.vars) });
        return () => 0;
      }
    }
  }

  // ---------------------------------------------------------------- expressions

  ex(e: Expr): Ev {
    switch (e.t) {
      case "num": {
        const v = e.v;
        return () => v;
      }
      case "str":
      case "color": {
        const v = e.v;
        return () => v;
      }
      case "bool": {
        const v = e.v ? 1 : 0;
        return () => v;
      }
      case "na":
        return () => NaN;
      case "id":
        return this.ident(e.name, e.pos);
      case "member":
        return this.memberValue(e);
      case "call":
        return this.call(e);
      case "hist":
        return this.hist(e as Extract<Expr, { t: "hist" }>);
      case "un": {
        const a = this.ex(e.e);
        const pos = e.pos;
        if (e.op === "not") return () => (truth(a()) ? 0 : 1);
        return () => {
          const v = a();
          return typeof v === "number" ? -v : rt(`CANNOT NEGATE ${typeName(v)}`, pos);
        };
      }
      case "bin":
        return this.binary(e);
      case "cond": {
        const k = this.ex(e.c);
        const a = this.ex(e.a);
        const b = this.ex(e.b);
        return () => (truth(k()) ? a() : b());
      }
      case "tuple": {
        const items = e.items.map((x) => this.ex(x));
        const out = new Array<unknown>(items.length);
        return () => {
          for (let i = 0; i < items.length; i++) out[i] = items[i]();
          return out;
        };
      }
    }
  }

  private ident(name: string, pos: Pos): Ev {
    const c = this.c;
    const v = this.scope.lookup(name);
    if (v) {
      if (v.kind === "input") {
        const val = v.val;
        return () => val;
      }
      if (v.kind === "src") return this.seriesRead(v.src as string);
      const S = c.slots;
      const slot = v.slot;
      return () => S[slot];
    }
    if (SERIES_NAMES.has(name)) return this.seriesRead(name);
    return rt(`UNKNOWN NAME ${name.toUpperCase()}`, pos);
  }

  /** The current bar's value of a bar series. */
  private seriesRead(name: string): Ev {
    const c = this.c;
    switch (name) {
      case "close":
        return () => c.c[c.bar];
      case "open":
        return () => c.o[c.bar];
      case "high":
        return () => c.h[c.bar];
      case "low":
        return () => c.l[c.bar];
      case "volume":
        return () => c.v[c.bar];
      default: {
        const g = seriesAt(c, name);
        return () => g(c.bar);
      }
    }
  }

  private memberValue(e: Extract<Expr, { t: "member" }>): Ev {
    const c = this.c;
    const name = this.dotted(e)?.join(".") ?? "";
    if (name === "math.pi") return () => Math.PI;
    if (name === "math.e") return () => Math.E;
    if (name === "barstate.isfirst") return () => (c.bar === 0 ? 1 : 0);
    if (name === "barstate.islast") return () => (c.bar === c.n - 1 ? 1 : 0);
    if (name.startsWith("color.")) {
      const col = COLORS[name.slice(6)];
      if (col) return () => col;
    }
    return rt(`UNKNOWN NAME ${name.toUpperCase()}`, e.pos);
  }

  private dotted(e: Expr): string[] | null {
    if (e.t === "id") return [e.name];
    if (e.t === "member") {
      const p = this.dotted(e.obj);
      return p ? [...p, e.name] : null;
    }
    return null;
  }

  /** `x[n]`. */
  private hist(e: Extract<Expr, { t: "hist" }>): Ev {
    const c = this.c;
    const name = (e.obj as Extract<Expr, { t: "id" }>).name;
    const kEv = this.ex(e.idx);
    const lit = e.idx.t === "num" ? Math.floor(e.idx.v) : undefined;
    const pos = e.pos;
    const v = this.scope.lookup(name);
    if (v && v.kind === "input") {
      const val = v.val;
      return () => {
        const k = lookback(kEv(), pos);
        return k !== k || k > c.bar ? NaN : val;
      };
    }
    const seriesName = v ? (v.kind === "src" ? v.src : undefined) : name;
    if (seriesName !== undefined) {
      const g = seriesAt(c, seriesName);
      return () => {
        const k = lookback(kEv(), pos);
        if (k !== k || k > c.bar) return NaN;
        return g(c.bar - k);
      };
    }
    const slot = (v as VarB).slot;
    const S = c.slots;
    const need = lit !== undefined ? lit : LIMITS.lookback;
    c.histCap[slot] = Math.max(c.histCap[slot], need);
    return () => {
      const k = lookback(kEv(), pos);
      if (k === 0) return S[slot];
      if (k !== k || k > c.bar) return NaN;
      const H = c.hist[slot] as unknown[];
      return H[(c.bar - k) % H.length];
    };
  }

  private binary(e: Extract<Expr, { t: "bin" }>): Ev {
    const l = this.ex(e.l);
    const r = this.ex(e.r);
    const pos = e.pos;
    switch (e.op) {
      case "+":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? a + b : addSlow(a, b, pos);
        };
      case "-":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? a - b : numErr("-", a, b, pos);
        };
      case "*":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? a * b : numErr("*", a, b, pos);
        };
      case "/":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? (b === 0 ? NaN : a / b) : numErr("/", a, b, pos);
        };
      case "%":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? (b === 0 ? NaN : a % b) : numErr("%", a, b, pos);
        };
      case "<":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? (a < b ? 1 : 0) : cmpSlow("<", a, b, pos);
        };
      case "<=":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? (a <= b ? 1 : 0) : cmpSlow("<=", a, b, pos);
        };
      case ">":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? (a > b ? 1 : 0) : cmpSlow(">", a, b, pos);
        };
      case ">=":
        return () => {
          const a = l();
          const b = r();
          return typeof a === "number" && typeof b === "number" ? (a >= b ? 1 : 0) : cmpSlow(">=", a, b, pos);
        };
      case "==":
        // NaN !== NaN, so a comparison with na is false
        return () => (l() === r() ? 1 : 0);
      case "!=":
        return () => {
          const a = l();
          const b = r();
          if (a !== a || b !== b) return 0; // a comparison with na is false (also for !=)
          return a !== b ? 1 : 0;
        };
      case "and":
        return () => (truth(l()) && truth(r()) ? 1 : 0);
      case "or":
        return () => (truth(l()) || truth(r()) ? 1 : 0);
    }
  }

  // ---------------------------------------------------------------- calls

  private call(e: Extract<Expr, { t: "call" }>): Ev {
    const callee = e.callee;
    if (callee.t === "id") {
      const f = this.funcs.get(callee.name);
      if (f && !this.scope.lookup(callee.name)) return this.userCall(f, e);
      return this.builtin(callee.name, e);
    }
    const path = callee.t === "member" ? this.dotted(callee) : null;
    if (callee.t === "member" && path && !this.scope.lookup(path[0])) {
      const name = path.join(".");
      if (path[0] === "lib" && path.length === 2) return this.libCall(path[1], e);
      return this.builtin(name, e);
    }
    return this.methodCall(callee as Extract<Expr, { t: "member" }>, e);
  }

  private constDefault(def: string): Ev {
    const v = defaultValue(def);
    return () => v;
  }

  /** The argument evaluators of a built-in call, one per parameter (defaults filled in) plus the extra variadic ones. */
  private argEvs(name: string, e: Extract<Expr, { t: "call" }>): { evs: Ev[]; slots: (Expr | undefined)[] } {
    const b = BY_NAME.get(name);
    const params = b?.params ?? [];
    const pl: ParamLike[] = params.map((p) => ({ name: p.name, optional: p.def !== undefined }));
    const m = matchArgs(name.toUpperCase(), pl, !!b?.variadic, e.args);
    if ("msg" in m) return rt(m.msg, e.pos);
    const evs: Ev[] = m.slots.map((x, i) => (x ? this.ex(x) : this.constDefault(params[i].def as string)));
    for (const x of m.extra) evs.push(this.ex(x));
    return { evs, slots: m.slots };
  }

  private builtin(name: string, e: Extract<Expr, { t: "call" }>): Ev {
    const c = this.c;
    const pos = e.pos;
    if (name === "indicator" || OUTPUT_NAMES.has(name)) {
      const o = this.output(name, e);
      if (o) return o;
    }
    if (name === "request") return this.requestCall(e);
    if (name.startsWith("ta.")) return this.taCall(name.slice(3), e);

    const { evs } = this.argEvs(name, e);
    // fast paths
    if (name === "na") {
      const a = evs[0];
      return () => {
        const x = a();
        return typeof x === "number" ? (x !== x ? 1 : 0) : x === undefined || x === null ? 1 : 0;
      };
    }
    if (name === "nz") {
      const a = evs[0];
      const b = evs[1];
      return () => {
        const x = a();
        return typeof x === "number" && x !== x ? b() : x;
      };
    }
    const m1 = MATH1[name];
    if (m1) {
      const a = evs[0];
      return () => {
        const x = a();
        return typeof x === "number" ? m1(x) : rt(`EXPECTED A NUMBER, GOT ${typeName(x)}`, pos);
      };
    }
    if (name === "str.tostring" && e.args.length > 0 && this.isBoolish(e.args[0].value)) {
      const a = evs[0];
      return () => (truth(a()) ? "true" : "false");
    }
    const impl = FN[name];
    if (!impl) return rt(`UNKNOWN NAME ${name.toUpperCase()}`, pos);
    const buf = new Array<unknown>(evs.length);
    return () => {
      for (let i = 0; i < evs.length; i++) buf[i] = evs[i]();
      try {
        return impl(c, buf);
      } catch (err) {
        return withPos(err, pos);
      }
    };
  }

  private methodCall(callee: Extract<Expr, { t: "member" }>, e: Extract<Expr, { t: "call" }>): Ev {
    const c = this.c;
    const pos = e.pos;
    const recv = this.ex(callee.obj);
    const evs = e.args.map((a) => this.ex(a.value));
    const method = callee.name;
    return () => {
      const r = recv();
      const ns = methodNs(r);
      const b = BY_NAME.get(`${ns}.${method}`);
      const impl = methodImpl(r, method);
      const params = b?.params ?? [];
      const args: unknown[] = [r];
      for (let i = 0; i < evs.length; i++) args.push(evs[i]());
      for (let i = args.length; i < params.length; i++) {
        const d = params[i].def;
        if (d === undefined) rt(`${ns.toUpperCase()}.${method.toUpperCase()} NEEDS MORE ARGUMENTS`, pos);
        args.push(defaultValue(d));
      }
      try {
        return impl(c, args);
      } catch (err) {
        return withPos(err, pos);
      }
    };
  }

  private userCall(f: FuncB, e: Extract<Expr, { t: "call" }>): Ev {
    const c = this.c;
    const def = f.def;
    const pl: ParamLike[] = def.params.map((p) => ({ name: p.name, optional: p.def !== undefined }));
    const m = matchArgs(def.name.toUpperCase(), pl, false, e.args);
    if ("msg" in m) return rt(m.msg, e.pos);
    // arguments are compiled in the CALLER's scope
    const argEvs: Ev[] = m.slots.map((x, i) => {
      if (x) return this.ex(x);
      const d = def.params[i].def as Expr;
      return this.ex(d);
    });
    // the body is compiled in a fresh copy: own slots, own ta states
    const saved = this.scope;
    const globalsView = new BScope(null);
    globalsView.vars = f.globals;
    const fscope = new BScope(globalsView);
    const pslots = def.params.map((p) => {
      const slot = this.newSlot(false);
      fscope.vars.set(p.name, { kind: "param", slot });
      return slot;
    });
    this.scope = fscope;
    const last = def.body[def.body.length - 1];
    const hasValue = last.t === "expr";
    // compile the statements first (they declare the variables the last line may read), then the result line
    const rest = this.seq((hasValue ? def.body.slice(0, -1) : def.body).map((s) => this.stmt(s)));
    const lastEv = hasValue ? this.ex(last.e) : null;
    this.scope = saved;
    const S = c.slots;
    return () => {
      for (let i = 0; i < pslots.length; i++) S[pslots[i]] = argEvs[i]();
      rest();
      return lastEv ? lastEv() : NaN;
    };
  }

  // ---------------------------------------------------------------- ta.*

  /** A constant number the compiler can work out now (literal, input, simple arithmetic), or undefined. */
  private tryConst(e: Expr | undefined): number | undefined {
    if (!e) return undefined;
    if (e.t === "num") return e.v;
    if (e.t === "un" && e.op === "-") {
      const v = this.tryConst(e.e);
      return v === undefined ? undefined : -v;
    }
    if (e.t === "id") {
      const v = this.scope.lookup(e.name);
      return v && v.kind === "input" && typeof v.val === "number" ? v.val : undefined;
    }
    if (e.t === "bin" && (e.op === "+" || e.op === "-" || e.op === "*")) {
      const a = this.tryConst(e.l);
      const b = this.tryConst(e.r);
      if (a === undefined || b === undefined) return undefined;
      return e.op === "+" ? a + b : e.op === "-" ? a - b : a * b;
    }
    return undefined;
  }

  private taCall(name: string, e: Extract<Expr, { t: "call" }>): Ev {
    const pos = e.pos;
    const { evs, slots } = this.argEvs(`ta.${name}`, e);
    const hint: TaHint = {};
    const li = TA_LEN_PARAM[name];
    if (li !== undefined) {
      const n = this.tryConst(slots[li]);
      if (n !== undefined && n >= 1 && n <= LIMITS.lookback) hint.len = n;
      else if (slots[li] === undefined && name === "change") hint.len = 1;
    }
    if (name === "valuewhen") {
      const k = this.tryConst(slots[2]);
      hint.occ = slots[2] === undefined ? 0 : k;
    }
    const fn: TaFn = makeTa(name, this.c, hint);
    this.c.states.push(fn);
    const buf = new Array<unknown>(evs.length);
    return () => {
      for (let i = 0; i < evs.length; i++) buf[i] = evs[i]();
      try {
        return fn.step(buf);
      } catch (err) {
        return withPos(err, pos);
      }
    };
  }

  // ---------------------------------------------------------------- lib.<ID>

  private libCall(id: string, e: Extract<Expr, { t: "call" }>): Ev {
    const c = this.c;
    const def = findIndicator(id);
    if (!def) return rt(`UNKNOWN INDICATOR LIB.${id.toUpperCase()}`, e.pos);
    const pl: ParamLike[] = def.params.map((p) => ({ name: p.name, optional: true }));
    const m = matchArgs(`LIB.${def.id}`, pl, false, e.args);
    if ("msg" in m) return rt(m.msg, e.pos);
    const params = m.slots.map((x) => (x ? this.constNumber(x) : NaN));
    const site: LibSite = { id: def.id, params, outs: [] };
    c.libs.push(site);
    if (def.outputs.length === 1) return () => site.outs[0][c.bar];
    const out = new Array<unknown>(def.outputs.length);
    return () => {
      for (let j = 0; j < out.length; j++) out[j] = site.outs[j][c.bar];
      return out;
    };
  }

  /** Evaluate a constant expression now (settings are fixed, so inputs count as constants). */
  private constEval(e: Expr): unknown {
    return this.ex(e)();
  }
  private constNumber(e: Expr): number {
    const v = this.constEval(e);
    return typeof v === "number" ? v : rt("EXPECTED A NUMBER", e.pos);
  }
  private constText(e: Expr | undefined, fallback: string): string {
    if (!e) return fallback;
    const v = this.constEval(e);
    return typeof v === "string" ? v : fallback;
  }

  // ---------------------------------------------------------------- request

  private requestCall(e: Extract<Expr, { t: "call" }>): Ev {
    const c = this.c;
    const m = matchArgs("REQUEST", [{ name: "symbol", optional: false }, { name: "timeframe", optional: false }, { name: "expr", optional: false }], false, e.args);
    if ("msg" in m) return rt(m.msg, e.pos);
    const slots = m.slots;
    const symbol = this.constText(slots[0], "");
    const tfRaw = this.constText(slots[1], "");
    const timeframe = tfRaw === "" ? "" : (TIMEFRAMES[tfRaw] ?? rt(`BAD TIMEFRAME ${tfRaw.toUpperCase()}`, e.pos));
    // the expression runs in its OWN context whose bars are the other series
    const sub = new Ctx(0);
    const b2 = new Builder(sub, this.checked, this.inputs);
    b2.scope = this.scope;
    const ev = b2.ex(slots[2] as Expr);
    const key = `${symbol}|${timeframe}`;
    const site: ReqSite = { key, symbol, timeframe, sub, ev, vals: new Float64Array(0), map: new Int32Array(0), err: "" };
    c.requests.push(site);
    const pos = e.pos;
    return () => {
      if (site.err) rt(site.err, pos);
      const k = site.map[c.bar];
      return k === undefined || k < 0 ? NaN : site.vals[k];
    };
  }

  // ---------------------------------------------------------------- outputs

  private newOut(kind: OutRec["kind"], title: string, style: string, hasValues: boolean): OutRec {
    const o: OutRec = {
      kind,
      title,
      style,
      values: hasValues ? new Float64Array(this.c.cap).fill(NaN) : null,
      a: -1,
      b: -1,
      color: null,
      colorSet: false,
      colors: null,
    };
    this.c.outputs.push(o);
    return o;
  }

  /** Remember the colour used on this bar; only keep a per-bar list when it actually changes. */
  private static setColor(o: OutRec, bar: number, col: string | null): void {
    if (o.colors) {
      o.colors[bar] = col;
      return;
    }
    if (!o.colorSet) {
      o.colorSet = true;
      o.color = col;
      return;
    }
    if (col !== o.color) {
      o.colors = [];
      o.colors[bar] = col;
    }
  }

  /** plot, hline, fill, bgcolor, plotshape, alert, alertcondition, indicator. Returns null if `name` is not one of them. */
  private output(name: string, e: Extract<Expr, { t: "call" }>): Ev | null {
    const c = this.c;
    const pos = e.pos;
    if (name === "indicator") return () => NaN;
    const { evs, slots } = this.argEvs(name, e);
    const params = BY_NAME.get(name)?.params ?? [];
    const slotOf = (pn: string) => slots[params.findIndex((p) => p.name === pn)];
    const textArg = (pn: string, fb: string) => this.constText(slotOf(pn), fb);

    if (name === "plot") {
      const o = this.newOut("plot", textArg("title", ""), textArg("style", "line"), true);
      const lw = slotOf("linewidth");
      o.linewidth = lw ? this.constNumber(lw as Expr) : 1;
      const h = new PlotH(c.outputs.length - 1);
      const series = evs[0];
      const colorEv = slotOf("color") ? evs[2] : null;
      return () => {
        const v = series();
        if (typeof v !== "number") rt(`PLOT NEEDS A NUMBER, GOT ${typeName(v)}`, pos);
        (o.values as Float64Array)[c.bar] = v;
        if (colorEv) Builder.setColor(o, c.bar, colorOrNull(colorEv()));
        return h;
      };
    }
    if (name === "hline") {
      const o = this.newOut("hline", textArg("title", ""), textArg("linestyle", "dashed"), false);
      o.price = this.constNumber(slots[0] as Expr);
      const col = slotOf("color") ? colorOrNull(this.constEval(slotOf("color") as Expr)) : null;
      o.color = col;
      o.colorSet = true;
      return () => NaN;
    }
    if (name === "fill") {
      const o = this.newOut("fill", "", "", false);
      const e1 = evs[0];
      const e2 = evs[1];
      const colorEv = slotOf("color") ? evs[2] : null;
      return () => {
        const a = e1();
        const b = e2();
        if (!(a instanceof PlotH) || !(b instanceof PlotH)) rt("FILL NEEDS TWO PLOTS", pos);
        o.a = (a as PlotH).idx;
        o.b = (b as PlotH).idx;
        Builder.setColor(o, c.bar, colorEv ? colorOrNull(colorEv()) : null);
        return NaN;
      };
    }
    if (name === "bgcolor") {
      const o = this.newOut("bgcolor", "", "", true);
      const colorEv = evs[0];
      return () => {
        const col = colorOrNull(colorEv());
        if (col !== null) (o.values as Float64Array)[c.bar] = 1;
        // record na too: a bar with no background is a colour change (colors entry null), as in the Python port
        Builder.setColor(o, c.bar, col);
        return NaN;
      };
    }
    if (name === "plotshape") {
      const loc = textArg("location", "abovebar");
      const o = this.newOut("shape", textArg("title", ""), textArg("style", "triangleup"), true);
      o.location = loc;
      o.text = textArg("text", "");
      const cond = evs[0];
      const colorEv = slotOf("color") ? evs[4] : null;
      // `absolute`: a number (not a true / false) is the price to draw at
      const absolutePrice = loc === "absolute" && !this.isBoolish(e.args.find((a) => a.name === undefined || a.name === "cond")?.value as Expr);
      return () => {
        const v = cond();
        if (truth(v)) {
          (o.values as Float64Array)[c.bar] = absolutePrice && typeof v === "number" ? v : 1;
          if (colorEv) Builder.setColor(o, c.bar, colorOrNull(colorEv()));
        }
        return NaN;
      };
    }
    if (name === "alert") {
      const st = { last: -1 };
      c.states.push(st);
      const msg = evs[0];
      return () => {
        const text = textOf(msg());
        if (st.last !== c.bar) {
          st.last = c.bar;
          c.alerts.push({ bar: c.bar, message: text });
          if (c.alerts.length > 2 * LIMITS.alerts) c.alerts.splice(0, c.alerts.length - LIMITS.alerts);
        }
        return NaN;
      };
    }
    if (name === "alertcondition") {
      const title = textArg("title", "");
      const message = textArg("message", "");
      const rec = { title, message, values: new Uint8Array(c.cap) };
      c.conditions.push(rec);
      const cond = evs[0];
      return () => {
        rec.values[c.bar] = truth(cond()) ? 1 : 0;
        return NaN;
      };
    }
    return null;
  }

  // ---------------------------------------------------------------- tiny static analysis

  /** Is this expression certainly a true / false value? */
  private isBoolish(e: Expr | undefined): boolean {
    if (!e) return false;
    switch (e.t) {
      case "bool":
        return true;
      case "un":
        return e.op === "not";
      case "bin":
        return ["and", "or", "==", "!=", "<", "<=", ">", ">="].includes(e.op);
      case "cond":
        return this.isBoolish(e.a) && this.isBoolish(e.b);
      case "id":
        return this.scope.lookup(e.name)?.bool === true;
      case "member":
        return (this.dotted(e)?.join(".") ?? "").startsWith("barstate.");
      case "call": {
        const name = this.dotted(e.callee)?.join(".") ?? "";
        return BY_NAME.get(name)?.ret === "bool";
      }
      default:
        return false;
    }
  }
}

// ---------------------------------------------------------------- inputs

/** Turn the host's overrides (by title) into the value of every input, applying the clamping rules of spec 1.5. */
export function resolveInputs(defs: InputDef[], overrides: Record<string, unknown> | undefined): Map<string, unknown> {
  const out = new Map<string, unknown>();
  for (const d of defs) {
    const ov = overrides?.[d.title];
    const given = ov !== undefined && ov !== null;
    switch (d.kind) {
      case "int":
      case "float": {
        let v = d.defval as number;
        if (given) {
          if (typeof ov !== "number" || !Number.isFinite(ov)) throw new ScriptRuntimeError(`INPUT ${d.title.toUpperCase()} NEEDS A NUMBER`);
          v = d.kind === "int" ? Math.round(ov) : ov;
        }
        if (d.min !== undefined && v < d.min) v = d.min;
        if (d.max !== undefined && v > d.max) v = d.max;
        out.set(d.title, v);
        break;
      }
      case "bool": {
        let v = d.defval as boolean;
        if (given) {
          if (typeof ov !== "boolean" && ov !== 0 && ov !== 1) throw new ScriptRuntimeError(`INPUT ${d.title.toUpperCase()} NEEDS TRUE OR FALSE`);
          v = ov === true || ov === 1;
        }
        out.set(d.title, v ? 1 : 0);
        break;
      }
      case "string":
      case "symbol":
      case "source":
      case "timeframe": {
        let v = d.defval as string;
        if (given) {
          if (typeof ov !== "string") throw new ScriptRuntimeError(`INPUT ${d.title.toUpperCase()} NEEDS TEXT`);
          v = ov;
        }
        if (d.kind === "timeframe") {
          const tf = Object.prototype.hasOwnProperty.call(TIMEFRAMES, v) ? TIMEFRAMES[v] : null;
          if (!tf) throw new ScriptRuntimeError(`BAD TIMEFRAME ${v.toUpperCase()}`);
          v = tf;
        } else if (d.options && !d.options.includes(v)) {
          throw new ScriptRuntimeError(`INPUT ${d.title.toUpperCase()}: ${v.toUpperCase()} IS NOT ONE OF THE OPTIONS`);
        }
        out.set(d.title, v);
        break;
      }
    }
  }
  return out;
}
