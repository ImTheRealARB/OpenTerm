import { describe, expect, it } from "vitest";
import { parseCommand } from "./parser";
import { matchSources, srcToken, takeSource } from "./srcArg";
import { settingsArgs } from "../settings/commands";
import { DEFAULTS, diffFromDefaults, normalize } from "../settings/schema";

const FNS = new Set(["GP", "Q", "FA", "N", "SETTINGS"]);
const p = (s: string) => parseCommand(s, (c) => FNS.has(c));

describe("SRC= in the command grammar", () => {
  it("pins the source and leaves the other words alone", () => {
    expect(p("AAPL GP 5Y SRC=NASDAQ")).toMatchObject({ ok: true, security: { symbol: "AAPL" }, fn: "GP", args: ["5Y"], source: "nasdaq" });
    expect(p("AAPL Q SRC=kite")).toMatchObject({ fn: "Q", args: [], source: "kite" });
    expect(p("AAPL SRC=yahoo")).toMatchObject({ ok: true, security: { symbol: "AAPL" }, source: "yahoo" });
  });
  it("can sit anywhere after the first word", () => {
    expect(p("AAPL src=nasdaq GP 5Y")).toMatchObject({ fn: "GP", args: ["5Y"], source: "nasdaq" });
    expect(p("Q AAPL MSFT SRC=yahoo")).toMatchObject({ fn: "Q", args: ["AAPL", "MSFT"], source: "yahoo" });
    expect(p("2: AAPL GP SRC=nasdaq")).toMatchObject({ target: 2, source: "nasdaq" });
  });
  it("PRED keeps its own SRC=POLY|KALSHI|ALL argument (a market, not a data source)", () => {
    const FN = (c: string) => c === "PRED";
    expect(parseCommand("PRED SRC=POLY", FN)).toMatchObject({ ok: true, fn: "PRED", args: ["SRC=POLY"] });
    expect(parseCommand("PRED SRC=POLY", FN)).not.toHaveProperty("source", expect.anything());
    expect(srcToken("PRED SRC=PO")).toBeNull();
  });
  it("no pin leaves the field off", () => {
    expect(p("AAPL GP 5Y")).not.toHaveProperty("source", expect.anything());
  });
  it("refuses an empty, malformed or repeated pin with a plain message", () => {
    expect(p("AAPL GP SRC=")).toMatchObject({ ok: false, error: expect.stringContaining("NEEDS A SOURCE NAME") });
    expect(p("AAPL GP SRC=a-b")).toMatchObject({ ok: false, error: "BAD SOURCE NAME: A-B" });
    expect(p("AAPL GP SRC=a SRC=b")).toMatchObject({ ok: false, error: "ONE SRC= PER COMMAND" });
  });
  it("the first word is never a pin (it stays a symbol, as EURUSD=X is)", () => {
    expect(p("SRC=NASDAQ GP")).not.toHaveProperty("source", expect.anything());
  });
});

describe("srcArg helpers", () => {
  it("takeSource lower-cases the name", () => {
    expect(takeSource(["AAPL", "GP", "SRC=NASDAQ"])).toEqual({ tokens: ["AAPL", "GP"], source: "nasdaq" });
  });
  it("srcToken finds the partial name only on the last word", () => {
    expect(srcToken("AAPL GP SRC=NAS")).toBe("NAS");
    expect(srcToken("AAPL GP SRC=")).toBe("");
    expect(srcToken("AAPL GP")).toBeNull();
    expect(srcToken("SRC=N")).toBeNull();
  });
  it("matchSources ranks prefixes before substrings", () => {
    const all = [{ name: "yahoo", label: "Yahoo Finance" }, { name: "nasdaq", label: "Nasdaq" }, { name: "nasdaq_screener", label: "Nasdaq screener" }, { name: "kite", label: "Zerodha Kite" }];
    expect(matchSources("nas", all).map((s) => s.name)).toEqual(["nasdaq", "nasdaq_screener"]);
    expect(matchSources("zer", all).map((s) => s.name)).toEqual(["kite"]);
    expect(matchSources("", all)).toHaveLength(4);
  });
});

describe("SETTINGS SOURCE", () => {
  it("sets, clears and resets a per-capability preference", () => {
    const set = settingsArgs(["SOURCE", "HISTORY", "NASDAQ"], DEFAULTS);
    expect(set).toMatchObject({ ok: true, next: { sources: { history: "nasdaq" } } });
    const next = (set as { next: typeof DEFAULTS }).next;
    expect(diffFromDefaults(next).sources).toEqual({ history: "nasdaq" });
    expect(settingsArgs(["SOURCE", "HISTORY", "DEFAULT"], next)).toMatchObject({ ok: true, next: { sources: {} } });
    expect(settingsArgs(["SOURCE", "RESET"], next)).toMatchObject({ ok: true, next: { sources: {} } });
    expect(settingsArgs(["SOURCE", "NEWS", "finnhub"], DEFAULTS)).toMatchObject({ next: { sources: { news_symbol: "finnhub" } } });
  });
  it("refuses a half-typed command and keeps defaults free of the field", () => {
    expect(settingsArgs(["SOURCE", "HISTORY"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["SOURCE", "HISTORY", "a b"], DEFAULTS)).toMatchObject({ ok: false });
    expect(diffFromDefaults(DEFAULTS)).not.toHaveProperty("sources");
  });
  it("round-trips through normalize and drops a bad entry", () => {
    expect(normalize({ sources: { history: "nasdaq" } }).settings.sources).toEqual({ history: "nasdaq" });
    const bad = normalize({ sources: { history: "No Way" } });
    expect(bad.settings.sources).toEqual({}) ;
    expect(bad.errors).toContain("sources.history");
  });
});
