/** Lexer, parser and checker tests: what the language accepts and the exact error texts. */
import { describe, expect, it } from "vitest";
import { lex } from "./lexer";
import { parse } from "./parser";
import { compile } from "./index";
import { compileErrors } from "./testkit";
import type { Expr, Stmt } from "./ast";

const kinds = (src: string) => lex(src).map((t) => (t.k === "op" || t.k === "kw" || t.k === "id" ? t.s : t.k));
const errOf = (src: string) => {
  try {
    parse(src);
  } catch (e) {
    return (e as { errors: { msg: string; line: number; col: number }[] }).errors[0];
  }
  throw new Error("expected a syntax error");
};
const msgs = (src: string) => compileErrors(src).map((e) => e.msg);

describe("lexer", () => {
  it("emits indent and dedent tokens", () => {
    expect(kinds("if a\n    b\nc\n")).toEqual(["if", "a", "nl", "indent", "b", "nl", "dedent", "c", "nl", "eof"]);
  });
  it("closes every open block at the end", () => {
    expect(kinds("if a\n    if b\n        c\n")).toEqual(["if", "a", "nl", "indent", "if", "b", "nl", "indent", "c", "nl", "dedent", "dedent", "eof"]);
  });
  it("ignores comments and blank lines", () => {
    expect(kinds("// hello\n\na = 1 // tail\n\n")).toEqual(["a", "=", "num", "nl", "eof"]);
  });
  it("a tab counts as 4 spaces", () => {
    expect(kinds("if a\n\tb\n    c\n")).toEqual(["if", "a", "nl", "indent", "b", "nl", "c", "nl", "dedent", "eof"]);
  });
  it("ignores newlines inside brackets", () => {
    expect(kinds("f(1,\n  2,\n      3)\n")).toEqual(["f", "(", "num", ",", "num", ",", "num", ")", "nl", "eof"]);
  });
  it("continues a line that ends with a binary operator or a comma", () => {
    expect(kinds("a = 1 +\n    2\n")).toEqual(["a", "=", "num", "+", "num", "nl", "eof"]);
    expect(kinds("a = b and\n c\n")).toEqual(["a", "=", "b", "and", "c", "nl", "eof"]);
  });
  it("reads numbers, strings with escapes and colours", () => {
    const t = lex('x = [1.5, .5, 1e-3, "a\\nb", \'q\', #FF0000, #00ff0080]\n');
    expect(t.filter((x) => x.k === "num").map((x) => x.v)).toEqual([1.5, 0.5, 0.001]);
    expect(t.filter((x) => x.k === "str").map((x) => x.s)).toEqual(["a\nb", "q"]);
    expect(t.filter((x) => x.k === "color").map((x) => x.s)).toEqual(["#ff0000", "#00ff0080"]);
  });
  it("`=>` and `==` are single tokens", () => {
    expect(kinds("f(a) =>\n    a == 1\n")).toEqual(["f", "(", "a", ")", "=>", "nl", "indent", "a", "==", "num", "nl", "dedent", "eof"]);
  });
  it("errors", () => {
    expect(errOf('a = "oops\n').msg).toBe("UNTERMINATED STRING");
    expect(errOf("a = 1 $ 2\n").msg).toBe("UNEXPECTED CHARACTER $");
    expect(errOf("a = #12\n").msg).toContain("BAD COLOUR");
    expect(errOf("if a\n        b\n    c\n").msg).toBe("BAD INDENT");
    expect(errOf("f(1,\n").msg).toBe("EXPECTED )");
    expect(errOf("a = 12abc\n").msg).toContain("BAD NUMBER");
  });
  it("errors carry line and column", () => {
    const e = errOf("a = 1\nb = 2 $\n");
    expect([e.line, e.col]).toEqual([2, 7]);
  });
});

const first = (src: string): Stmt => parse(src).body[0];
const exprOf = (src: string): Expr => {
  const s = first(src);
  if (s.t !== "expr") throw new Error("not an expression statement");
  return s.e;
};

describe("parser", () => {
  it("precedence: * over +", () => {
    const e = exprOf("1 + 2 * 3\n");
    expect(e).toMatchObject({ t: "bin", op: "+", r: { t: "bin", op: "*" } });
  });
  it("not binds looser than ==", () => {
    expect(exprOf("not a == b\n")).toMatchObject({ t: "un", op: "not", e: { t: "bin", op: "==" } });
  });
  it("and binds tighter than or", () => {
    expect(exprOf("a or b and c\n")).toMatchObject({ t: "bin", op: "or", r: { t: "bin", op: "and" } });
  });
  it("unary minus binds tighter than *", () => {
    expect(exprOf("-a * b\n")).toMatchObject({ t: "bin", op: "*", l: { t: "un", op: "-" } });
  });
  it("ternary is right associative", () => {
    expect(exprOf("a ? b : c ? d : e\n")).toMatchObject({ t: "cond", b: { t: "cond" } });
  });
  it("history, member and call chains", () => {
    expect(exprOf("close[1]\n")).toMatchObject({ t: "hist", obj: { t: "id", name: "close" } });
    expect(exprOf("ta.sma(close, 3)\n")).toMatchObject({ t: "call", callee: { t: "member", name: "sma" } });
    expect(exprOf("arr.push(1)\n")).toMatchObject({ t: "call", callee: { t: "member", name: "push", obj: { t: "id", name: "arr" } } });
  });
  it("named arguments", () => {
    const e = exprOf('plot(x, "T", color = color.red)\n');
    expect(e).toMatchObject({ t: "call" });
    if (e.t === "call") expect(e.args.map((a) => a.name)).toEqual([undefined, undefined, "color"]);
  });
  it("`na` alone is the value, `na(x)` is a call", () => {
    expect(exprOf("na\n")).toMatchObject({ t: "na" });
    expect(exprOf("na(x)\n")).toMatchObject({ t: "call", callee: { t: "id", name: "na" } });
  });
  it("declarations", () => {
    expect(first("x = 1\n")).toMatchObject({ t: "decl", isVar: false });
    expect(first("var x = 1\n")).toMatchObject({ t: "decl", isVar: true });
    expect(first("x := 1\n")).toMatchObject({ t: "assign", op: ":=" });
    expect(first("x += 1\n")).toMatchObject({ t: "assign", op: "+=" });
    expect(first("[a, b] = f(1)\n")).toMatchObject({ t: "tdecl", names: ["a", "b"] });
  });
  it("if / else if / else", () => {
    const s = first("if a\n    b\nelse if c\n    d\nelse\n    e\n");
    expect(s).toMatchObject({ t: "if", else_: [{ t: "if", else_: [{ t: "expr" }] }] });
  });
  it("for with step, while, break, continue", () => {
    expect(first("for i = 1 to 10 by 2\n    break\n")).toMatchObject({ t: "for", v: "i", by: { t: "num" }, body: [{ t: "break" }] });
    expect(first("while a\n    continue\n")).toMatchObject({ t: "while", body: [{ t: "continue" }] });
  });
  it("functions: one line, block, defaults", () => {
    expect(first("f(a, b = 2) => a + b\n")).toMatchObject({ t: "func", name: "f", params: [{ name: "a" }, { name: "b", def: { t: "num" } }], body: [{ t: "expr" }] });
    expect(first("f(a) =>\n    x = a\n    x * 2\n")).toMatchObject({ t: "func", body: [{ t: "decl" }, { t: "expr" }] });
  });
  it("a tuple as the last line of a function", () => {
    expect(first("f(a) =>\n    [a, a * 2]\n")).toMatchObject({ t: "func", body: [{ t: "expr", e: { t: "tuple" } }] });
  });
  it("errors", () => {
    expect(errOf("a = \n").msg).toBe("EXPECTED EXPRESSION");
    expect(errOf("f(1\n").msg).toBe("EXPECTED )");
    expect(errOf("if a\nb\n").msg).toBe("EXPECTED AN INDENTED BLOCK");
    expect(errOf("a b\n").msg).toBe("UNEXPECTED B");
    expect(errOf("f(a = 1, 2)\n").msg).toContain("POSITIONAL ARGUMENT AFTER A NAMED ONE");
  });
});

describe("checker", () => {
  it("accepts the spec example", () => {
    const r = compile(`indicator("RSI bands", overlay=false)
len = input.int(14, "Length", min=1, max=200)
src = input.source(close, "Source")
r = ta.rsi(src, len)
p = plot(r, "RSI", color = r > 70 ? color.red : color.orange)
hline(70, "Upper")
hline(30, "Lower")
var crosses = 0
if ta.crossover(r, 30)
    crosses += 1
    alert("RSI up through 30")
alertcondition(ta.crossunder(r, 70), "RSI down", "RSI fell below 70")
`);
    if (!r.ok) throw new Error(JSON.stringify(r.errors));
    expect(r.program.meta.title).toBe("RSI bands");
    expect(r.program.meta.inputs.map((i) => i.title)).toEqual(["Length", "Source"]);
    expect(r.program.meta.conditions).toEqual([{ title: "RSI down", message: "RSI fell below 70" }]);
  });
  it("unknown names", () => {
    expect(msgs("a = foo + 1\n")).toContain("UNKNOWN NAME FOO");
    expect(msgs("a = foo(1)\n")).toContain("UNKNOWN NAME FOO");
    expect(msgs("a = ta.nope(1)\n")).toContain("UNKNOWN NAME TA.NOPE");
  });
  it("assignment rules", () => {
    expect(msgs("x := 1\n")).toContain("X IS NOT DECLARED (USE = FIRST)");
    expect(msgs("x = 1\nx = 2\n")).toContain("X IS ALREADY DECLARED");
    expect(msgs("x = 1\nif close > 1\n    x = 2\n")).toContain("X IS ALREADY DECLARED");
    expect(msgs("close = 1\n")).toContain("CLOSE IS A BUILT-IN NAME");
  });
  it("argument counts", () => {
    expect(msgs("a = ta.sma(close)\n")).toContain("TA.SMA TAKES 2 ARGUMENTS");
    expect(msgs("a = ta.sma(close, 1, 2)\n")).toContain("TA.SMA TAKES 2 ARGUMENTS");
    expect(msgs('plot()\n')).toContain("PLOT TAKES 1 TO 5 ARGUMENTS");
    expect(msgs("a = math.max(1)\n")).toContain("MATH.MAX TAKES 2 OR MORE ARGUMENTS");
    expect(msgs("a = ta.sma(close, nope=3)\n")).toContain("UNKNOWN ARGUMENT NOPE FOR TA.SMA");
  });
  it("ta calls cannot run inside a loop", () => {
    expect(msgs("for i = 1 to 3\n    a = ta.sma(close, 2)\n")).toContain("TA CALLS CANNOT RUN INSIDE A LOOP");
    expect(msgs("f(x) => ta.sma(x, 2)\nwhile close > 1\n    a = f(close)\n    break\n")).toContain("TA CALLS CANNOT RUN INSIDE A LOOP");
    // inside an `if` is fine
    expect(compile("if close > 1\n    a = ta.sma(close, 2)\n").ok).toBe(true);
  });
  it("history only on a name", () => {
    expect(msgs("a = ta.sma(close, 2)[1]\n")).toEqual(expect.arrayContaining([expect.stringContaining("ASSIGN TO A VARIABLE FIRST")]));
    expect(compile("a = close[1]\n").ok).toBe(true);
  });
  it("strategies are part 2", () => {
    expect(msgs('strategy("x")\n')).toContain("STRATEGIES COME IN PART 2 (NOT BUILT YET)");
  });
  it("indicator must come first", () => {
    expect(msgs('a = 1\nindicator("x")\n')).toContain("INDICATOR MUST BE THE FIRST STATEMENT");
  });
  it("functions: no recursion, top level only, unique, defaults are literals", () => {
    expect(msgs("f(x) => f(x)\n")).toContain("F CANNOT CALL ITSELF");
    expect(msgs("if close > 1\n    f(x) => x\n")).toContain("FUNCTIONS CAN ONLY BE DEFINED AT THE TOP LEVEL");
    expect(msgs("f(x) => x\nf(y) => y\n")).toContain("F IS ALREADY DECLARED");
    expect(msgs("f(x, y = close) => x\n")).toEqual(expect.arrayContaining([expect.stringContaining("DEFAULT VALUE MUST BE")]));
    expect(msgs("f(x) => x\na = f()\n")).toContain("F TAKES 1 ARGUMENT");
  });
  it("a function cannot change a global", () => {
    expect(msgs("g = 1\nf() =>\n    g := 2\n    g\n")).toContain("G IS A GLOBAL: A FUNCTION CANNOT CHANGE IT");
  });
  it("tuples", () => {
    expect(msgs("[a, b] = ta.macd(close, 1, 2, 3)\n")).toContain("TA.MACD GIVES 3 VALUES, NOT 2");
    expect(msgs("a = ta.macd(close, 1, 2, 3)\n").join(" ")).toContain("TUPLE");
    expect(msgs("x = [1, 2]\n").join(" ")).toContain("TUPLE");
    expect(compile("f(a) =>\n    [a, a * 2]\n[p, q] = f(1)\n").ok).toBe(true);
    expect(msgs("f(a) =>\n    [a, a * 2]\n[p, q, r] = f(1)\n")).toContain("F GIVES 2 VALUES, NOT 3");
  });
  it("loops: break and continue", () => {
    expect(msgs("break\n")).toContain("BREAK OUTSIDE A LOOP");
  });
  it("inputs", () => {
    expect(msgs('a = input.int(1, "A")\nb = input.int(2, "A")\n')).toContain("DUPLICATE INPUT TITLE A");
    expect(msgs('if close > 1\n    a = input.int(1, "A")\n')).toContain("INPUTS CAN ONLY BE DECLARED AT THE TOP LEVEL");
    expect(msgs("a = input.int(1)\n")).toContain("INPUT.INT TAKES 2 TO 5 ARGUMENTS");
    expect(msgs('a = input.int(1, "")\n').join(" ")).toContain("TITLE");
    expect(msgs('a = input.int(close, "A")\n').join(" ")).toContain("CONSTANT");
    expect(msgs('a = input.string("x", "A", array.from("a", "b"))\n')).toContain("THE DEFAULT IS NOT ONE OF THE OPTIONS");
    expect(msgs('a = input.timeframe("7x", "A")\n')).toContain("BAD TIMEFRAME 7X");
    expect(msgs('a = input.int(1, "A")\na := 2\n')).toContain("A IS AN INPUT AND CANNOT BE CHANGED");
  });
  it("constants where the spec asks for them", () => {
    expect(msgs('hline(close, "x")\n').join(" ")).toContain("MUST BE A CONSTANT");
    expect(msgs('plot(close, "a" + str.tostring(close))\n').join(" ")).toContain("MUST BE A CONSTANT");
    expect(msgs('alertcondition(close > 1, "x" + str.tostring(close), "m")\n').join(" ")).toContain("MUST BE A CONSTANT");
    expect(msgs('if close > 1\n    hline(1)\n')).toContain("HLINE CAN ONLY BE USED AT THE TOP LEVEL");
  });
  it("request", () => {
    expect(msgs('x = 1\na = request("", "1D", x)\n')).toContain("REQUEST CAN ONLY USE BAR DATA, INPUTS AND BUILT-INS");
    expect(msgs('a = request("", "1D", plot(close))\n')).toContain("REQUEST CAN ONLY USE BAR DATA, INPUTS AND BUILT-INS");
    expect(msgs('a = request("", "2x", close)\n')).toContain("BAD TIMEFRAME 2X");
    expect(msgs("a = request(str.tostring(close), \"1D\", close)\n").join(" ")).toContain("CONSTANT");
    const ok = compile('s = input.symbol("AAPL", "Sym")\na = request(s, "D", ta.sma(close, 5))\n');
    if (!ok.ok) throw new Error(JSON.stringify(ok.errors));
    expect(ok.program.meta.requests).toEqual([{ symbol: "AAPL", timeframe: "1D" }]);
  });
  it("lib", () => {
    expect(msgs("a = lib.NOPE(3)\n")).toContain("UNKNOWN INDICATOR LIB.NOPE");
    expect(msgs("n = close\na = lib.SMA(n)\n").join(" ")).toContain("CONSTANT");
    expect(msgs("[a, b] = lib.MACD(12, 26, 9)\n")).toContain("LIB.MACD GIVES 3 VALUES, NOT 2");
    const ok = compile('n = input.int(20, "N")\na = lib.SMA(n)\n');
    if (!ok.ok) throw new Error(JSON.stringify(ok.errors));
    expect(ok.program.meta.usesLib).toBe(true);
  });
  it("shape / style / position names are checked", () => {
    expect(msgs('plot(close, "x", style = "wobbly")\n')).toContain("BAD PLOT STYLE WOBBLY");
    expect(msgs('plotshape(close > 1, "x", style = "star")\n')).toContain("BAD SHAPE STYLE STAR");
    expect(msgs('plotshape(close > 1, "x", location = "up")\n')).toContain("BAD LOCATION UP");
    expect(msgs('t = table.new("middle", 1, 1)\n')).toContain("BAD TABLE POSITION MIDDLE");
  });
  it("fill needs plots", () => {
    expect(msgs("fill(1, 2)\n").join(" ")).toContain("FILL NEEDS TWO PLOTS");
  });
  it("too many outputs and too big a script", () => {
    const many = Array.from({ length: 65 }, (_, i) => `plot(close + ${i})`).join("\n") + "\n";
    expect(msgs(many).join(" ")).toContain("TOO MANY OUTPUTS");
    const big = "a = " + Array.from({ length: 1600 }, () => "1").join(" + ") + "\n";
    expect(msgs(big).join(" ")).toContain("SCRIPT TOO BIG");
    expect(msgs("a = 1 // " + "x".repeat(20_000) + "\n")).toContain("SOURCE TOO LONG (MAX 20000 CHARACTERS)");
  });
  it("void values cannot be used", () => {
    expect(msgs('a = alert("x")\n').join(" ")).toContain("NO VALUE");
  });
  it("methods", () => {
    expect(compile("a = array.new(0)\na.push(1)\nb = a.size()\n").ok).toBe(true);
    expect(msgs("a = array.new(0)\na.nonsense()\n")).toContain("UNKNOWN METHOD NONSENSE");
  });
  it("errors come back sorted by position", () => {
    const e = compileErrors("a = foo\nb = bar\n");
    expect(e.map((x) => x.line)).toEqual([1, 2]);
  });
});
