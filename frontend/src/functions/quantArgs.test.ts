import { describe, expect, it } from "vitest";

/*
 * Phase 15 step 1 (spec docs/specs/PHASE_15.md): command-line parsers for RISK, PORT OPT, PORT ATTR, FACT, QL, ALPHA, CORR REGIME and KITE,
 * plus `quantBody`, which turns the string params into the typed JSON body of `POST /api/quant/{fn}`. Pure (no window): the module does
 * not exist yet, so every test is `it.fails` through a variable-path import (tsc would reject a missing module). The build step that makes
 * them pass (step 3 for RISK/OPT/ATTR, 4 for FACT/QL, 5 for ALPHA/REGIME, 7 for KITE) switches them to plain `it` with a static import.
 */
const MOD = "./quantArgs";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const load = async (): Promise<any> => import(/* @vite-ignore */ MOD);

describe("riskArgs", () => {
  it.fails("takes a portfolio word and KEY=VALUE pairs, keys lower-cased", async () => {
    const { riskArgs } = await load();
    expect(riskArgs(["main", "range=5y", "conf=99", "hor=5", "bench=QQQ"])).toEqual({
      params: { portfolio: "MAIN", range: "5y", conf: "99", hor: "5", bench: "QQQ" },
      bad: [],
    });
    expect(riskArgs([])).toEqual({ params: {}, bad: [] });
  });
  it.fails("reports anything else instead of guessing", async () => {
    const { riskArgs } = await load();
    expect(riskArgs(["MAIN", "FOO=1", "x y"]).bad).toEqual(["FOO=1", "x y"]);
    expect(riskArgs(["RANGE="]).bad).toEqual(["RANGE="]);
  });
});

describe("optArgs", () => {
  it.fails("method, cap, lookback, rf and tc are recognised; the method word is upper-cased", async () => {
    const { optArgs } = await load();
    expect(optArgs(["MAIN", "method=rp", "cap=0.2", "lookback=126", "rf=0.04", "tc=0.001"]).params).toEqual({
      portfolio: "MAIN", method: "RP", cap: "0.2", lookback: "126", rf: "0.04", tc: "0.001",
    });
  });
});

describe("attrArgs", () => {
  it.fails("a portfolio and benchmark run the attribution", async () => {
    const { attrArgs } = await load();
    expect(attrArgs(["MAIN", "bench=qqq", "range=1y"])).toEqual({ params: { portfolio: "MAIN", bench: "QQQ", range: "1y" }, bad: [] });
  });
  it.fails("ADD and DEL edit the stored valuations", async () => {
    const { attrArgs } = await load();
    expect(attrArgs(["MAIN", "ADD", "2025-01-01", "VALUE=10000", "FLOW=500"])).toEqual({
      params: { portfolio: "MAIN" }, action: { kind: "add", date: "2025-01-01", value: "10000", flow: "500" }, bad: [],
    });
    expect(attrArgs(["MAIN", "DEL", "2025-01-01"]).action).toEqual({ kind: "del", date: "2025-01-01" });
    expect(attrArgs(["MAIN", "ADD", "2025-01-01"]).bad).toContain("VALUE=");
    expect(attrArgs(["MAIN", "ADD", "JAN", "VALUE=1"]).bad).toContain("JAN");
  });
});

describe("factArgs", () => {
  it.fails("one symbol (or portfolio) and a range", async () => {
    const { factArgs } = await load();
    expect(factArgs(["aapl", "range=3y"])).toEqual({ params: { symbol: "AAPL", range: "3y" }, bad: [] });
    expect(factArgs(["AAPL", "MSFT"]).bad).toEqual(["MSFT"]);
  });
});

describe("qlArgs", () => {
  it.fails("the calculator word, its symbols and its KEY=VALUE inputs", async () => {
    const { qlArgs } = await load();
    expect(qlArgs(["garch", "aapl", "h=5"])).toEqual({ params: { calc: "GARCH", symbols: ["AAPL"], h: "5" }, bad: [] });
    expect(qlArgs(["coint", "ko", "pep"]).params).toEqual({ calc: "COINT", symbols: ["KO", "PEP"] });
    expect(qlArgs(["dsr", "sr=1.5", "n=100", "t=1000"]).params).toEqual({ calc: "DSR", sr: "1.5", n: "100", t: "1000" });
    expect(qlArgs(["event", "aapl", "date=2026-01-15", "win=-5,5"]).params).toEqual({ calc: "EVENT", symbols: ["AAPL"], date: "2026-01-15", win: "-5,5" });
  });
  it.fails("an unknown calculator is reported, a missing one too", async () => {
    const { qlArgs } = await load();
    expect(qlArgs(["nope", "aapl"]).bad).toEqual(["NOPE"]);
    expect(qlArgs([]).bad).toEqual(["CALCULATOR"]);
  });
});

describe("alphaArgs", () => {
  it.fails("universe, range, family and horizons", async () => {
    const { alphaArgs } = await load();
    expect(alphaArgs(["universe=syn", "range=2y", "family=alpha101", "h=1,5,10"]).params).toEqual({ universe: "SYN", range: "2y", family: "alpha101", h: "1,5,10" });
    expect(alphaArgs(["universe=wl:tech"]).params).toEqual({ universe: "WL:TECH" });
    expect(alphaArgs(["universe=list:aapl,msft,nvda"]).params).toEqual({ universe: "LIST:AAPL,MSFT,NVDA" });
    expect(alphaArgs(["TOP100"]).params).toEqual({ universe: "TOP100" });
  });
});

describe("regimeArgs", () => {
  it.fails("a list, a window and an edge threshold", async () => {
    const { regimeArgs } = await load();
    expect(regimeArgs(["wl:tech", "win=60", "edge=0.5"])).toEqual({ params: { list: "WL:TECH", win: "60", edge: "0.5" }, bad: [] });
    expect(regimeArgs([])).toEqual({ params: {}, bad: [] });
  });
});

describe("quantBody", () => {
  it.fails("numbers become numbers, horizons a list, symbols stay a list", async () => {
    const { quantBody } = await load();
    expect(quantBody("risk", { portfolio: "MAIN", conf: "99", hor: "5" })).toEqual({ portfolio: "MAIN", conf: 99, hor: 5 });
    expect(quantBody("alpha", { universe: "SYN", h: "1,5" })).toEqual({ universe: "SYN", h: [1, 5] });
    expect(quantBody("ql", { calc: "COINT", symbols: ["KO", "PEP"], sr: "1.5" })).toEqual({ calc: "COINT", symbols: ["KO", "PEP"], sr: 1.5 });
    expect(quantBody("opt", { portfolio: "MAIN", method: "RP", cap: "0.2", lookback: "126" })).toEqual({ portfolio: "MAIN", method: "RP", cap: 0.2, lookback: 126 });
  });
});

describe("kiteArgs", () => {
  it.fails("LOGIN, STATUS and LOGOUT, nothing else", async () => {
    const { kiteArgs } = await load();
    expect(kiteArgs([])).toEqual({ params: { action: "status" }, bad: [] });
    expect(kiteArgs(["login"]).params).toEqual({ action: "login" });
    expect(kiteArgs(["LOGOUT"]).params).toEqual({ action: "logout" });
    expect(kiteArgs(["buy"]).bad).toEqual(["BUY"]);
  });
});
