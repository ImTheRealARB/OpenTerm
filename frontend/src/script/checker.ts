/**
 * OpenTerm Script checker: reads the syntax tree and reports every mistake it can find BEFORE the script runs
 * (unknown names, wrong argument counts, `:=` on an undeclared variable, a `ta.*` call inside a loop, ...).
 * It also collects the script's "meta": title, inputs, requests, alert conditions.
 *
 * It does not produce any run-time code: compile.ts builds that from the same tree. The rules here and the scoping rules
 * in compile.ts must agree (the compiler trusts that the checker passed).
 *
 * Scoping rules (spec 1.3):
 *   - `name = expr` declares in the current block; it is an error if the name already exists in this block or an
 *     enclosing block (no shadowing). A user function body is its own world: its parameters and locals may reuse a name
 *     of a global, and it can READ globals declared before the function, but cannot assign them.
 *   - Names of built-ins (`close`, `plot`, `ta`, ...) cannot be declared.
 */
import type { Arg, Ast, Expr, Param, Pos, ScriptError, Stmt } from "./ast";
import { arityText, matchArgs, type ParamLike } from "./args";
import { findIndicator } from "../chart/library/catalog";
import { BUILTINS, BY_NAME, LIMITS, METHOD_NAMESPACES, SOURCES, TIMEFRAMES, type Builtin } from "./names";

// ---------------------------------------------------------------- public shapes

export type InputKind = "int" | "float" | "bool" | "string" | "source" | "symbol" | "timeframe";

/** One setting of a script (the host builds the inputs form from these). Overrides are passed by `title`. */
export interface InputDef {
  title: string;
  kind: InputKind;
  defval: number | string | boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
}

export interface ProgramMeta {
  title: string;
  overlay: boolean;
  maxLabels: number;
  inputs: InputDef[];
  /** `request(...)` calls with their DEFAULT symbol / timeframe (an input may change them: see Program.resolveRequests). */
  requests: { symbol: string; timeframe: string }[];
  conditions: { title: string; message: string }[];
  usesLib: boolean;
}

export interface Checked {
  errors: ScriptError[];
  meta: ProgramMeta;
  /** The `input.*(...)` call node -> its definition (compile.ts reads it to apply overrides). */
  inputDefs: Map<Expr, InputDef>;
}

// ---------------------------------------------------------------- static types (best effort)

/** num bool str color void plot label line box table array map any tuple:N */
type Ty = string;
const isTuple = (t: Ty) => t.startsWith("tuple:");

function retTy(r: Builtin["ret"]): Ty {
  return r === "number" ? "num" : r === "string" ? "str" : r;
}

// ---------------------------------------------------------------- scopes

type VarKind = "var" | "input" | "src" | "param" | "loop";
interface VarInfo {
  ty: Ty;
  kind: VarKind;
  /** Declared inside the function being checked (false = a global seen from inside a function). */
  local: boolean;
  /** For an input variable: its definition (so a constant text can be read from the default). */
  input?: InputDef;
}

class Scope {
  vars = new Map<string, VarInfo>();
  constructor(
    public parent: Scope | null,
    /** The root scope of a user function: lookups for DECLARATION conflicts stop here. */
    public fnRoot = false,
  ) {}
  lookup(name: string): VarInfo | undefined {
    for (let s: Scope | null = this; s; s = s.parent) {
      const v = s.vars.get(name);
      if (v) return v;
    }
    return undefined;
  }
  /** Is `name` already declared in this block or an enclosing one (up to the function root)? */
  clashes(name: string): boolean {
    for (let s: Scope | null = this; s; s = s.parent) {
      if (s.vars.has(name)) return true;
      if (s.fnRoot) return false;
    }
    return false;
  }
}

// ---------------------------------------------------------------- names

/** Every name that begins a built-in: a variable cannot take one of these. */
const RESERVED = new Set<string>(["lib", "strategy"]);
const NAMESPACES = new Set<string>(["lib"]);
for (const b of BUILTINS) {
  const dot = b.name.indexOf(".");
  RESERVED.add(dot < 0 ? b.name : b.name.slice(0, dot));
  if (dot >= 0) NAMESPACES.add(b.name.slice(0, dot));
}

/** Which arguments must be constants (decided when the script is compiled, not per bar). */
const CONST_PARAMS: Record<string, string[] | "all"> = {
  indicator: "all",
  hline: "all",
  plot: ["title", "linewidth", "style"],
  plotshape: ["title", "style", "location", "text"],
  alertcondition: ["title", "message"],
  "input.int": "all",
  "input.float": "all",
  "input.bool": "all",
  "input.string": "all",
  "input.source": "all",
  "input.symbol": "all",
  "input.timeframe": "all",
};
const OUTPUT_FNS = new Set(["plot", "hline", "fill", "bgcolor", "plotshape"]);
/** Functions a `request` expression may call (besides `ta.*` and `lib.*`). */
const REQUEST_OK_PREFIX = ["math.", "ta.", "lib."];
const REQUEST_OK_FNS = new Set(["na", "nz"]);

const up = (s: string) => s.toUpperCase();

interface FuncInfo {
  name: string;
  params: Param[];
  hasTa: boolean;
  /** Node count when this function is expanded at one call site. */
  weight: number;
  outputs: number;
  ret: Ty;
}

export function check(ast: Ast): Checked {
  return new Checker().run(ast);
}

class Checker {
  errors: ScriptError[] = [];
  meta: ProgramMeta = { title: "", overlay: false, maxLabels: 500, inputs: [], requests: [], conditions: [], usesLib: false };
  inputDefs = new Map<Expr, InputDef>();
  private funcs = new Map<string, FuncInfo>();
  private scope = new Scope(null);
  private fn: FuncInfo | null = null;
  private loopDepth = 0;
  private blockDepth = 0;
  private inRequest = false;
  private nodes = 0;
  private outputs = 0;
  private titles = new Set<string>();

  private err(msg: string, pos: Pos): void {
    this.errors.push({ msg, line: pos.line, col: pos.col });
  }

  run(ast: Ast): Checked {
    ast.body.forEach((s, i) => this.stmt(s, i === 0));
    if (this.nodes > LIMITS.nodes) this.err(`SCRIPT TOO BIG (MAX ${LIMITS.nodes} NODES)`, { line: 1, col: 1 });
    if (this.outputs > LIMITS.outputs) this.err(`TOO MANY OUTPUTS (MAX ${LIMITS.outputs} PLOTS, LINES AND SHAPES)`, { line: 1, col: 1 });
    return { errors: this.errors, meta: this.meta, inputDefs: this.inputDefs };
  }

  private get topLevel(): boolean {
    return this.blockDepth === 0 && this.fn === null && !this.inRequest;
  }

  // ---------------------------------------------------------------- statements

  private block(stmts: Stmt[]): void {
    const saved = this.scope;
    this.scope = new Scope(saved);
    this.blockDepth++;
    for (const s of stmts) this.stmt(s, false);
    this.blockDepth--;
    this.scope = saved;
  }

  private declare(name: string, info: VarInfo, pos: Pos): void {
    if (RESERVED.has(name) || NAMESPACES.has(name)) return this.err(`${up(name)} IS A BUILT-IN NAME`, pos);
    if (this.funcs.has(name)) return this.err(`${up(name)} IS A FUNCTION`, pos);
    if (this.scope.clashes(name)) return this.err(`${up(name)} IS ALREADY DECLARED`, pos);
    this.scope.vars.set(name, info);
  }

  private stmt(s: Stmt, first: boolean): void {
    this.nodes++;
    switch (s.t) {
      case "decl": {
        let ty: Ty;
        let kind: VarKind = "var";
        let input: InputDef | undefined;
        if (s.value.t === "call" && isInputCall(s.value)) {
          if (!this.topLevel) this.err("INPUTS CAN ONLY BE DECLARED AT THE TOP LEVEL", s.value.pos);
          const def = this.inputCall(s.value);
          input = def ?? undefined;
          ty = def ? (def.kind === "int" || def.kind === "float" || def.kind === "source" ? "num" : def.kind === "bool" ? "bool" : "str") : "any";
          kind = def?.kind === "source" ? "src" : "input";
        } else {
          ty = this.expr(s.value);
          if (isTuple(ty)) this.err(`A TUPLE NEEDS [A, B] = ... (NOT ${up(s.name)} = ...)`, s.value.pos);
          if (ty === "void") this.err(`${up(s.name)} WOULD HAVE NO VALUE`, s.value.pos);
        }
        this.declare(s.name, { ty: isTuple(ty) || ty === "void" ? "any" : ty, kind, local: this.fn !== null, input }, s.pos);
        return;
      }
      case "tdecl": {
        const ty = this.expr(s.value);
        if (isTuple(ty)) {
          const n = Number(ty.slice(6));
          // wording shared with the Python port (docs/review/phase25_B.md), e.g. "TA.MACD GIVES 3 VALUES, NOT 2"
          const what = s.value.t === "call" ? (this.dotted(s.value.callee)?.join(".") ?? "THIS").toUpperCase() : "THIS";
          if (n !== s.names.length) this.err(`${what} GIVES ${n} VALUES, NOT ${s.names.length}`, s.pos);
        } else if (ty !== "any") {
          this.err("THE RIGHT SIDE OF [A, B] = MUST GIVE SEVERAL VALUES", s.value.pos);
        }
        const seen = new Set<string>();
        for (const n of s.names) {
          if (seen.has(n)) this.err(`${up(n)} GIVEN TWICE`, s.pos);
          seen.add(n);
          this.declare(n, { ty: "any", kind: "var", local: this.fn !== null }, s.pos);
        }
        return;
      }
      case "assign": {
        const v = this.scope.lookup(s.name);
        const ty = this.expr(s.value);
        if (isTuple(ty)) this.err("A TUPLE CANNOT BE ASSIGNED TO ONE VARIABLE", s.value.pos);
        if (!v) return this.err(`${up(s.name)} IS NOT DECLARED (USE = FIRST)`, s.pos);
        if (v.kind === "input" || v.kind === "src") return this.err(`${up(s.name)} IS AN INPUT AND CANNOT BE CHANGED`, s.pos);
        if (v.kind === "loop") return this.err(`${up(s.name)} IS A LOOP VARIABLE AND CANNOT BE CHANGED`, s.pos);
        if (this.fn && !v.local) return this.err(`${up(s.name)} IS A GLOBAL: A FUNCTION CANNOT CHANGE IT`, s.pos);
        if (v.ty !== ty) v.ty = "any";
        return;
      }
      case "expr": {
        const e = s.e;
        if (e.t === "call" && e.callee.t === "id" && e.callee.name === "indicator" && !first) {
          this.err("INDICATOR MUST BE THE FIRST STATEMENT", e.pos);
          return;
        }
        this.expr(e, { statement: true });
        return;
      }
      case "if": {
        const ty = this.expr(s.cond);
        if (isTuple(ty)) this.err("A TUPLE CANNOT BE A CONDITION", s.cond.pos);
        this.block(s.then);
        if (s.else_) this.block(s.else_);
        return;
      }
      case "for": {
        this.expr(s.from);
        this.expr(s.to);
        if (s.by) this.expr(s.by);
        const saved = this.scope;
        this.scope = new Scope(saved);
        this.declare(s.v, { ty: "num", kind: "loop", local: this.fn !== null }, s.pos);
        this.loopDepth++;
        this.blockDepth++;
        for (const b of s.body) this.stmt(b, false);
        this.blockDepth--;
        this.loopDepth--;
        this.scope = saved;
        return;
      }
      case "while": {
        this.expr(s.cond);
        this.loopDepth++;
        this.block(s.body);
        this.loopDepth--;
        return;
      }
      case "break":
      case "continue":
        if (this.loopDepth === 0) this.err(`${up(s.t)} OUTSIDE A LOOP`, s.pos);
        return;
      case "func":
        this.funcDef(s);
        return;
    }
  }

  private funcDef(s: Extract<Stmt, { t: "func" }>): void {
    if (!this.topLevel) return this.err("FUNCTIONS CAN ONLY BE DEFINED AT THE TOP LEVEL", s.pos);
    if (RESERVED.has(s.name) || NAMESPACES.has(s.name)) return this.err(`${up(s.name)} IS A BUILT-IN NAME`, s.pos);
    if (this.funcs.has(s.name) || this.scope.lookup(s.name)) return this.err(`${up(s.name)} IS ALREADY DECLARED`, s.pos);
    const info: FuncInfo = { name: s.name, params: s.params, hasTa: false, weight: 0, outputs: 0, ret: "any" };
    // parameters: unique names, defaults are literals
    const seen = new Set<string>();
    for (const p of s.params) {
      if (seen.has(p.name)) this.err(`PARAMETER ${up(p.name)} GIVEN TWICE`, p.pos);
      seen.add(p.name);
      if (RESERVED.has(p.name)) this.err(`${up(p.name)} IS A BUILT-IN NAME`, p.pos);
      if (p.def && !isLiteral(p.def)) this.err("A DEFAULT VALUE MUST BE A NUMBER, TEXT, TRUE, FALSE OR NA", p.def.pos);
    }
    // check the body once (in its own world), measuring its size and outputs
    const savedScope = this.scope;
    const savedNodes = this.nodes;
    const savedOutputs = this.outputs;
    this.scope = new Scope(savedScope, true);
    for (const p of s.params) this.scope.vars.set(p.name, { ty: "any", kind: "param", local: true });
    this.fn = info;
    this.nodes = 0;
    this.outputs = 0;
    this.blockDepth++;
    s.body.forEach((b, i) => {
      if (i === s.body.length - 1 && b.t === "expr") {
        this.nodes++;
        info.ret = this.expr(b.e, { tupleOk: true, statement: true });
      } else this.stmt(b, false);
    });
    this.blockDepth--;
    this.fn = null;
    info.weight = this.nodes + 1;
    info.outputs = this.outputs;
    this.scope = savedScope;
    this.nodes = savedNodes + 1;
    this.outputs = savedOutputs;
    this.funcs.set(s.name, info);
  }

  // ---------------------------------------------------------------- expressions

  private expr(e: Expr, o: { tupleOk?: boolean; statement?: boolean } = {}): Ty {
    this.nodes++;
    switch (e.t) {
      case "num":
      case "na":
        return "num";
      case "str":
        return "str";
      case "color":
        return "color";
      case "bool":
        return "bool";
      case "id":
        return this.ident(e);
      case "member":
        return this.memberValue(e);
      case "call":
        return this.call(e);
      case "hist": {
        if (e.obj.t !== "id") {
          this.err("ASSIGN TO A VARIABLE FIRST (HISTORY [N] WORKS ON A NAME)", e.pos);
          this.expr(e.obj);
          this.expr(e.idx);
          return "any";
        }
        const t = this.ident(e.obj);
        this.operand(e.idx);
        if (this.inRequest) return "num";
        return isTuple(t) ? "any" : t;
      }
      case "un": {
        this.operand(e.e);
        return e.op === "not" ? "bool" : "num";
      }
      case "bin": {
        const l = this.operand(e.l);
        const r = this.operand(e.r);
        if (e.op === "and" || e.op === "or" || e.op === "==" || e.op === "!=" || e.op === "<" || e.op === "<=" || e.op === ">" || e.op === ">=") return "bool";
        if (e.op === "+") return l === "num" && r === "num" ? "num" : l === "str" && r === "str" ? "str" : "any";
        return "num";
      }
      case "cond": {
        this.operand(e.c);
        const a = this.operand(e.a);
        const b = this.operand(e.b);
        return a === b ? a : "any";
      }
      case "tuple": {
        if (!o.tupleOk) this.err("A TUPLE [A, B] CAN ONLY BE THE LAST LINE OF A FUNCTION", e.pos);
        for (const it of e.items) this.operand(it);
        return `tuple:${e.items.length}`;
      }
    }
  }

  /** An expression used as a value inside another one: no tuples, no "nothing". */
  private operand(e: Expr): Ty {
    const t = this.expr(e);
    if (isTuple(t)) this.err("A TUPLE NEEDS [A, B] = ...", e.pos);
    else if (t === "void") this.err("THIS HAS NO VALUE TO USE", e.pos);
    return isTuple(t) || t === "void" ? "any" : t;
  }

  private ident(e: Extract<Expr, { t: "id" }>): Ty {
    const v = this.scope.lookup(e.name);
    if (v) {
      if (this.inRequest && v.kind !== "input" && v.kind !== "src") {
        this.err("REQUEST CAN ONLY USE BAR DATA, INPUTS AND BUILT-INS", e.pos);
      }
      return v.ty;
    }
    if (this.funcs.has(e.name)) {
      this.err(`${up(e.name)} IS A FUNCTION: CALL IT WITH ()`, e.pos);
      return "any";
    }
    const b = BY_NAME.get(e.name);
    if (b && b.kind === "var") return retTy(b.ret);
    if (b || NAMESPACES.has(e.name)) {
      this.err(`${up(e.name)} IS A FUNCTION: CALL IT WITH ()`, e.pos);
      return "any";
    }
    this.err(`UNKNOWN NAME ${up(e.name)}`, e.pos);
    return "any";
  }

  /** `a.b.c` as a dotted name if it is only identifiers, else null. */
  private dotted(e: Expr): string[] | null {
    if (e.t === "id") return [e.name];
    if (e.t === "member") {
      const p = this.dotted(e.obj);
      return p ? [...p, e.name] : null;
    }
    return null;
  }

  private memberValue(e: Extract<Expr, { t: "member" }>): Ty {
    const path = this.dotted(e);
    if (path && !this.scope.lookup(path[0])) {
      const name = path.join(".");
      const b = BY_NAME.get(name);
      if (b && b.kind === "var") return retTy(b.ret);
      if (b) {
        this.err(`${up(name)} IS A FUNCTION: CALL IT WITH ()`, e.pos);
        return "any";
      }
      if (!NAMESPACES.has(path[0]) && !this.funcs.has(path[0])) {
        this.err(`UNKNOWN NAME ${up(path[0])}`, e.pos);
        return "any";
      }
      this.err(`UNKNOWN NAME ${up(name)}`, e.pos);
      return "any";
    }
    this.err(`${up(e.name)} IS NOT A VALUE (METHODS NEED ())`, e.pos);
    this.expr(e.obj);
    return "any";
  }

  // ---------------------------------------------------------------- calls

  private call(e: Extract<Expr, { t: "call" }>): Ty {
    const callee = e.callee;
    // 1. plain name: user function or built-in function
    if (callee.t === "id") {
      const name = callee.name;
      if (name === "strategy") {
        this.err("STRATEGIES COME IN PART 2 (NOT BUILT YET)", e.pos);
        return "void";
      }
      const f = this.funcs.get(name);
      if (f && !this.scope.lookup(name)) return this.userCall(f, e);
      if (this.fn && this.fn.name === name) {
        this.err(`${up(name)} CANNOT CALL ITSELF`, e.pos); // no recursion (spec 1.4); wording shared with the Python port
        return "any";
      }
      const b = BY_NAME.get(name);
      if (b && b.kind === "fn") return this.builtinCall(b, name, e);
      if (this.scope.lookup(name)) {
        this.err(`${up(name)} IS NOT A FUNCTION`, e.pos);
        return "any";
      }
      this.err(`UNKNOWN NAME ${up(name)}`, e.pos);
      for (const a of e.args) this.expr(a.value);
      return "any";
    }
    if (callee.t !== "member") {
      this.err("EXPECTED A FUNCTION NAME BEFORE (", e.pos);
      return "any";
    }
    // 2. dotted name rooted at a namespace: ta.sma, math.max, lib.MACD ...
    const path = this.dotted(callee);
    if (path && !this.scope.lookup(path[0]) && (NAMESPACES.has(path[0]) || path.length > 1)) {
      const name = path.join(".");
      if (path[0] === "lib" && path.length === 2) return this.libCall(path[1], e);
      const b = BY_NAME.get(name);
      if (b && b.kind === "fn") return this.builtinCall(b, name, e);
      this.err(`UNKNOWN NAME ${up(name)}`, e.pos);
      for (const a of e.args) this.expr(a.value);
      return "any";
    }
    // 3. method call on a value: arr.push(x), h.delete()
    return this.methodCall(callee, e);
  }

  private methodCall(callee: Extract<Expr, { t: "member" }>, e: Extract<Expr, { t: "call" }>): Ty {
    this.operand(callee.obj);
    const cands: Builtin[] = [];
    for (const ns of METHOD_NAMESPACES) {
      const b = BY_NAME.get(`${ns}.${callee.name}`);
      if (b && b.kind === "fn") cands.push(b);
    }
    for (const a of e.args) {
      this.operand(a.value);
      if (a.name !== undefined) this.err("METHOD ARGUMENTS MUST BE POSITIONAL", a.pos);
    }
    if (cands.length === 0) {
      this.err(`UNKNOWN METHOD ${up(callee.name)}`, callee.pos);
      return "any";
    }
    const n = e.args.length + 1;
    const fits = cands.some((b) => {
      const min = (b.params ?? []).filter((p) => p.def === undefined).length;
      return n >= min && n <= (b.params ?? []).length;
    });
    if (!fits) {
      const min = Math.min(...cands.map((b) => (b.params ?? []).filter((p) => p.def === undefined).length)) - 1;
      const max = Math.max(...cands.map((b) => (b.params ?? []).length)) - 1;
      this.err(arityText(`.${up(callee.name)}`, Math.max(0, min), max), e.pos);
    }
    const rets = new Set(cands.map((b) => retTy(b.ret)));
    return rets.size === 1 ? [...rets][0] : "any";
  }

  private userCall(f: FuncInfo, e: Extract<Expr, { t: "call" }>): Ty {
    const params: ParamLike[] = f.params.map((p) => ({ name: p.name, optional: p.def !== undefined }));
    const m = matchArgs(up(f.name), params, false, e.args);
    for (const a of e.args) this.operand(a.value);
    if ("msg" in m) this.err(m.msg, m.arg?.pos ?? e.pos);
    if (f.hasTa) {
      if (this.loopDepth > 0 && !this.inRequest) this.err("TA CALLS CANNOT RUN INSIDE A LOOP", e.pos);
      if (this.fn) this.fn.hasTa = true;
    }
    this.nodes += f.weight;
    this.outputs += f.outputs;
    return f.ret;
  }

  private builtinCall(b: Builtin, name: string, e: Extract<Expr, { t: "call" }>): Ty {
    const display = up(name);
    const params: ParamLike[] = (b.params ?? []).map((p) => ({ name: p.name, optional: p.def !== undefined }));
    const m = matchArgs(display, params, !!b.variadic, e.args);
    const ok = !("msg" in m);
    if (name === "request") return this.requestCall(m, e);
    if (name.startsWith("input.")) {
      this.err(`ASSIGN THE INPUT TO A NAME: X = ${display}(...)`, e.pos);
      return retTy(b.ret);
    }
    if (b.topLevel && !this.topLevel) this.err(`${display} CAN ONLY BE USED AT THE TOP LEVEL`, e.pos);
    if (name === "indicator") {
      if (ok) this.indicatorMeta(m.slots, e);
      else this.err(m.msg, m.arg?.pos ?? e.pos);
      return "void";
    }
    if (b.stateful) {
      if (this.inRequest) {
        // inside request(...): evaluated on the other series, not per chart bar: fine
      } else {
        if (this.loopDepth > 0) this.err("TA CALLS CANNOT RUN INSIDE A LOOP", e.pos);
        if (this.fn) this.fn.hasTa = true;
      }
    }
    if (this.inRequest && !REQUEST_OK_FNS.has(name) && !REQUEST_OK_PREFIX.some((p) => name.startsWith(p))) {
      this.err("REQUEST CAN ONLY USE BAR DATA, INPUTS AND BUILT-INS", e.pos);
    }
    if (OUTPUT_FNS.has(name)) this.outputs++;

    // check the arguments
    if (!ok) this.err(m.msg, m.arg?.pos ?? e.pos);
    const constNames = CONST_PARAMS[name];
    const tys: Ty[] = [];
    for (const a of e.args) {
      tys.push(this.operand(a.value));
    }
    if (constNames) {
      for (const a of e.args) {
        const pname = ok ? paramNameOf(m, e.args, a, b) : a.name;
        if ((constNames === "all" || (pname && constNames.includes(pname))) && !this.isConst(a.value) && !(name.startsWith("input.source") && a.value.t === "id")) {
          this.err(`${up(pname ?? "ARGUMENT")} OF ${display} MUST BE A CONSTANT`, a.pos);
        }
      }
    }
    if (ok) this.specialChecks(b, name, m, e);
    return retTy(b.ret);
  }

  /** Per-function rules that need the matched arguments. */
  private specialChecks(b: Builtin, name: string, m: { slots: (Expr | undefined)[]; extra: Expr[] }, e: Extract<Expr, { t: "call" }>): void {
    const slotOf = (pname: string) => m.slots[(b.params ?? []).findIndex((p) => p.name === pname)];
    if (name === "plot") {
      const style = slotOf("style");
      if (style && style.t === "str" && !(["line", "stepline", "histogram", "columns", "circles", "area"] as string[]).includes(style.v)) {
        this.err(`BAD PLOT STYLE ${up(style.v)}`, style.pos);
      }
    } else if (name === "plotshape") {
      const style = slotOf("style");
      const loc = slotOf("location");
      const SHAPES = ["triangleup", "triangledown", "circle", "cross", "diamond", "arrowup", "arrowdown", "labelup", "labeldown"];
      if (style && style.t === "str" && !SHAPES.includes(style.v)) this.err(`BAD SHAPE STYLE ${up(style.v)}`, style.pos);
      if (loc && loc.t === "str" && !["abovebar", "belowbar", "absolute"].includes(loc.v)) this.err(`BAD LOCATION ${up(loc.v)}`, loc.pos);
    } else if (name === "table.new") {
      const pos = slotOf("position");
      if (pos && pos.t === "str" && !["top_left", "top_right", "bottom_left", "bottom_right"].includes(pos.v)) this.err(`BAD TABLE POSITION ${up(pos.v)}`, pos.pos);
    } else if (name === "alertcondition") {
      const title = slotOf("title");
      const msg = slotOf("message");
      const tv = title ? this.constString(title) : undefined;
      if (tv === undefined) this.err("ALERT TITLE MUST BE TEXT", e.pos);
      else {
        const mv = msg ? (this.constString(msg) ?? "") : "";
        if (this.meta.conditions.some((c) => c.title === tv)) this.err(`DUPLICATE ALERT CONDITION ${up(tv)}`, e.pos);
        else this.meta.conditions.push({ title: tv, message: mv });
      }
    } else if (name === "fill") {
      for (const pn of ["plot1", "plot2"]) {
        const x = slotOf(pn);
        if (x) {
          const t = this.peekTy(x);
          if (t !== "plot" && t !== "any") this.err("FILL NEEDS TWO PLOTS (USE P = PLOT(...) FIRST)", x.pos);
        }
      }
    }
  }

  /** Type of an expression that was already checked (no new errors): only identifiers and plot calls matter here. */
  private peekTy(e: Expr): Ty {
    if (e.t === "id") return this.scope.lookup(e.name)?.ty ?? "any";
    if (e.t === "num" || e.t === "bool" || e.t === "str" || e.t === "color" || e.t === "na") return "num";
    if (e.t === "call" && e.callee.t === "id" && e.callee.name === "plot") return "plot";
    return "any";
  }

  private indicatorMeta(slots: (Expr | undefined)[], e: Extract<Expr, { t: "call" }>): void {
    const title = slots[0];
    if (title && title.t === "str") this.meta.title = title.v;
    else this.err("INDICATOR TITLE MUST BE TEXT", e.pos);
    const ov = slots[1];
    if (ov && (ov.t === "bool" || ov.t === "num")) this.meta.overlay = ov.t === "bool" ? ov.v : ov.v !== 0;
    const ml = slots[2];
    if (ml && ml.t === "num") this.meta.maxLabels = Math.min(LIMITS.drawingsPerKind, Math.max(1, Math.floor(ml.v)));
  }

  // ---------------------------------------------------------------- inputs

  private inputCall(e: Extract<Expr, { t: "call" }>): InputDef | null {
    const callee = e.callee as Extract<Expr, { t: "member" }>;
    const name = `input.${callee.name}`;
    const b = BY_NAME.get(name);
    if (!b) {
      this.err(`UNKNOWN NAME ${up(name)}`, e.pos);
      return null;
    }
    const kind = callee.name as InputKind;
    const params: ParamLike[] = (b.params ?? []).map((p) => ({ name: p.name, optional: p.def !== undefined }));
    const m = matchArgs(up(name), params, false, e.args);
    if ("msg" in m) {
      this.err(m.msg, m.arg?.pos ?? e.pos);
      return null;
    }
    const lit = (pname: string): number | string | boolean | undefined => {
      const x = m.slots[(b.params ?? []).findIndex((p) => p.name === pname)];
      return x === undefined ? undefined : this.literalValue(x);
    };
    const slot = (pname: string) => m.slots[(b.params ?? []).findIndex((p) => p.name === pname)];
    for (const a of e.args) {
      // every argument must be a literal (a number, text, true / false, na, a bar-series name for input.source, or array.from(...) of text)
      const v = a.value;
      const isSrc = kind === "source" && v.t === "id" && (SOURCES as readonly string[]).includes(v.name);
      const isOpts = v.t === "call" && v.callee.t === "member" && this.dotted(v.callee)?.join(".") === "array.from";
      if (this.literalValue(v) === undefined && !isSrc && !isOpts) {
        // name the parameter, e.g. "DEFVAL MUST BE A CONSTANT" (wording shared with the Python port)
        const pi = m.slots.indexOf(v);
        const pname = pi >= 0 && b.params?.[pi] ? b.params[pi].name.toUpperCase() : "ARGUMENT";
        this.err(`${pname} MUST BE A CONSTANT`, a.pos);
      }
    }
    this.nodes += e.args.length;
    const title = lit("title");
    if (typeof title !== "string" || title === "") {
      this.err("AN INPUT NEEDS A TITLE (TEXT)", e.pos);
      return null;
    }
    if (this.titles.has(title)) this.err(`DUPLICATE INPUT TITLE ${up(title)}`, e.pos);
    this.titles.add(title);
    const dv = slot("defval");
    let def: InputDef;
    const num = (x: unknown): number | undefined => (typeof x === "number" && x === x ? x : undefined);
    if (kind === "int" || kind === "float") {
      const d = num(lit("defval"));
      if (d === undefined) {
        this.err(`${up(name)} NEEDS A NUMBER AS ITS DEFAULT`, dv?.pos ?? e.pos);
        return null;
      }
      def = { title, kind, defval: d };
      const mn = num(lit("min"));
      const mx = num(lit("max"));
      const st = num(lit("step"));
      if (mn !== undefined) def.min = mn;
      if (mx !== undefined) def.max = mx;
      if (st !== undefined) def.step = st;
      if (mn !== undefined && mx !== undefined && mn > mx) this.err("MIN IS ABOVE MAX", e.pos);
      if (kind === "int" && !Number.isInteger(d)) this.err("INPUT.INT NEEDS A WHOLE NUMBER", dv?.pos ?? e.pos);
    } else if (kind === "bool") {
      const d = lit("defval");
      if (typeof d !== "boolean" && d !== 0 && d !== 1) {
        this.err("INPUT.BOOL NEEDS TRUE OR FALSE", dv?.pos ?? e.pos);
        return null;
      }
      def = { title, kind, defval: d === true || d === 1 };
    } else if (kind === "source") {
      if (!dv || dv.t !== "id" || !(SOURCES as readonly string[]).includes(dv.name)) {
        this.err(`INPUT.SOURCE NEEDS ONE OF ${SOURCES.join(" ").toUpperCase()}`, dv?.pos ?? e.pos);
        return null;
      }
      def = { title, kind, defval: dv.name, options: [...SOURCES] };
    } else if (kind === "timeframe") {
      const d = lit("defval");
      const tf = typeof d === "string" ? (Object.prototype.hasOwnProperty.call(TIMEFRAMES, d) ? TIMEFRAMES[d] : null) : null;
      if (!tf) {
        this.err(`BAD TIMEFRAME ${up(String(d ?? ""))}`, dv?.pos ?? e.pos);
        return null;
      }
      def = { title, kind, defval: tf };
    } else {
      // string, symbol
      const d = lit("defval");
      if (typeof d !== "string") {
        this.err(`${up(name)} NEEDS TEXT AS ITS DEFAULT`, dv?.pos ?? e.pos);
        return null;
      }
      def = { title, kind, defval: d };
      const o = slot("options");
      if (kind === "string" && o && o.t !== "na") {
        const opts = this.optionList(o);
        if (!opts) this.err("OPTIONS MUST BE ARRAY.FROM(...) OF TEXT", o.pos);
        else {
          def.options = opts;
          if (!opts.includes(d)) this.err("THE DEFAULT IS NOT ONE OF THE OPTIONS", dv?.pos ?? e.pos);
        }
      }
    }
    this.meta.inputs.push(def);
    this.inputDefs.set(e, def);
    return def;
  }

  /** `array.from("a", "b")` as a list of text, or null. */
  private optionList(e: Expr): string[] | null {
    if (e.t !== "call" || e.callee.t !== "member" || this.dotted(e.callee)?.join(".") !== "array.from") return null;
    const out: string[] = [];
    for (const a of e.args) {
      if (a.value.t !== "str") return null;
      out.push(a.value.v);
    }
    return out;
  }

  private literalValue(e: Expr): number | string | boolean | undefined {
    if (e.t === "num") return e.v;
    if (e.t === "str") return e.v;
    if (e.t === "bool") return e.v;
    if (e.t === "na") return NaN;
    if (e.t === "un" && e.op === "-" && e.e.t === "num") return -e.e.v;
    return undefined;
  }

  // ---------------------------------------------------------------- constants

  /** Can the value be worked out when the script is compiled (no bar data)? */
  private isConst(e: Expr): boolean {
    switch (e.t) {
      case "num":
      case "str":
      case "color":
      case "bool":
      case "na":
        return true;
      case "id": {
        const v = this.scope.lookup(e.name);
        return v?.kind === "input";
      }
      case "member": {
        const p = this.dotted(e)?.join(".") ?? "";
        return p === "math.pi" || p === "math.e" || p.startsWith("color.");
      }
      case "un":
        return this.isConst(e.e);
      case "bin":
        return this.isConst(e.l) && this.isConst(e.r);
      case "cond":
        return this.isConst(e.c) && this.isConst(e.a) && this.isConst(e.b);
      case "call": {
        const name = this.dotted(e.callee)?.join(".") ?? "";
        const okFn = name.startsWith("math.") || name === "color.new" || name === "color.rgb" || name.startsWith("str.") || name === "nz" || name === "na";
        return okFn && e.args.every((a) => this.isConst(a.value));
      }
      default:
        return false;
    }
  }

  /** The text value of a constant expression, as far as the checker can tell (text literal, text input default, a + b). */
  private constString(e: Expr): string | undefined {
    if (e.t === "str") return e.v;
    if (e.t === "id") {
      const d = this.scope.lookup(e.name)?.input?.defval;
      return typeof d === "string" ? d : undefined;
    }
    if (e.t === "bin" && e.op === "+") {
      const a = this.constString(e.l);
      const b = this.constString(e.r);
      return a !== undefined && b !== undefined ? a + b : undefined;
    }
    return undefined;
  }
  // ---------------------------------------------------------------- request and lib

  private requestCall(m: { slots: (Expr | undefined)[]; extra: Expr[] } | { msg: string; arg?: Arg }, e: Extract<Expr, { t: "call" }>): Ty {
    if (this.inRequest) {
      this.err("REQUEST CANNOT BE NESTED", e.pos);
      return "num";
    }
    if ("msg" in m) {
      this.err(m.msg, m.arg?.pos ?? e.pos);
      for (const a of e.args) this.expr(a.value);
      return "num";
    }
    const [sym, tf, ex] = m.slots as Expr[];
    const sv = this.operandConstText(sym, "SYMBOL");
    const tv = this.operandConstText(tf, "TIMEFRAME");
    if (sv !== undefined && tv !== undefined) {
      const norm = tv === "" ? "" : Object.prototype.hasOwnProperty.call(TIMEFRAMES, tv) ? TIMEFRAMES[tv] : null;
      if (norm === null) this.err(`BAD TIMEFRAME ${up(tv)}`, tf.pos);
      else if (!this.meta.requests.some((r) => r.symbol === sv && r.timeframe === norm)) this.meta.requests.push({ symbol: sv, timeframe: norm });
    }
    const saved = this.inRequest;
    this.inRequest = true;
    const t = this.expr(ex);
    this.inRequest = saved;
    if (isTuple(t)) this.err("REQUEST GIVES ONE VALUE, NOT A TUPLE", ex.pos);
    return "num";
  }

  private operandConstText(e: Expr, what: string): string | undefined {
    this.operand(e);
    if (!this.isConst(e)) {
      this.err(`REQUEST ${what} MUST BE A CONSTANT OR AN INPUT`, e.pos);
      return undefined;
    }
    const v = this.constString(e);
    if (v === undefined) this.err(`REQUEST ${what} MUST BE TEXT`, e.pos);
    return v;
  }

  private libCall(id: string, e: Extract<Expr, { t: "call" }>): Ty {
    const def = findIndicator(id);
    this.meta.usesLib = true;
    if (!def) {
      this.err(`UNKNOWN INDICATOR LIB.${up(id)}`, e.pos);
      for (const a of e.args) this.expr(a.value);
      return "any";
    }
    const params: ParamLike[] = def.params.map((p) => ({ name: p.name, optional: true }));
    const m = matchArgs(`LIB.${up(def.id)}`, params, false, e.args);
    if ("msg" in m) this.err(m.msg, m.arg?.pos ?? e.pos);
    for (const a of e.args) {
      this.operand(a.value);
      if (!this.isConst(a.value)) this.err(`LIB.${up(def.id)} ARGUMENTS MUST BE CONSTANTS`, a.pos);
    }
    return def.outputs.length === 1 ? "num" : `tuple:${def.outputs.length}`;
  }
}

// ---------------------------------------------------------------- helpers

function isInputCall(e: Extract<Expr, { t: "call" }>): boolean {
  return e.callee.t === "member" && e.callee.obj.t === "id" && e.callee.obj.name === "input";
}

function isLiteral(e: Expr): boolean {
  return e.t === "num" || e.t === "str" || e.t === "bool" || e.t === "na" || e.t === "color" || (e.t === "un" && e.op === "-" && e.e.t === "num");
}

/** Which parameter name an argument fills (named: its name; positional: by position). */
function paramNameOf(_m: unknown, args: Arg[], a: Arg, b: Builtin): string | undefined {
  if (a.name !== undefined) return a.name;
  const k = args.filter((x) => x.name === undefined).indexOf(a);
  return b.params?.[k]?.name;
}
