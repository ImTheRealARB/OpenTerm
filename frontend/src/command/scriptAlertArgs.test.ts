import { describe, expect, it } from "vitest";
import { parseScriptAlertCmd } from "./scriptAlertArgs";

// The command line splits on spaces and keeps the quotes, so a quoted title arrives as several tokens.
const args = (s: string) => s.split(/\s+/).filter(Boolean);

describe("parseScriptAlertCmd", () => {
  it("is null for everything that is not a script alert (price, news, list, price delete)", () => {
    for (const s of ["", "AAPL > 200", "AAPL +5%", "NEWS RECALL AAPL", 'NEWS "script=x" AAPL', "DEL 3", "DEL N3", "DEL S1a2b3c4d", "CLEAR", "AAPL RSI14<30"]) {
      expect(parseScriptAlertCmd(args(s)), s).toBeNull();
    }
  });

  it("reads SCRIPT=NAME with no condition (the script's own alert() calls)", () => {
    expect(parseScriptAlertCmd(args("aapl script=rsi-cross"))).toEqual({ kind: "createScript", symbol: "AAPL", script: "RSI-CROSS", cond: null });
  });

  it("reads a quoted condition title with spaces, in either order, keeping its case", () => {
    const want = { kind: "createScript", symbol: "AAPL", script: "MY.RSI", cond: "RSI down" };
    expect(parseScriptAlertCmd(args('AAPL SCRIPT=my.rsi COND="RSI down"'))).toEqual(want);
    expect(parseScriptAlertCmd(args('AAPL COND="RSI down" SCRIPT=my.rsi'))).toEqual(want);
    expect(parseScriptAlertCmd(args("AAPL SCRIPT=my.rsi COND='RSI down'"))).toEqual(want);
  });

  it("reads a bare one-word condition and a title that holds the other keyword", () => {
    expect(parseScriptAlertCmd(args("AAPL SCRIPT=A COND=Cross"))).toMatchObject({ cond: "Cross" });
    expect(parseScriptAlertCmd(args('AAPL SCRIPT=A COND="SCRIPT=B up"'))).toMatchObject({ script: "A", cond: "SCRIPT=B up" });
  });

  it("uses the typed security when the command has none", () => {
    expect(parseScriptAlertCmd(args("SCRIPT=A"), { symbol: "MSFT" })).toMatchObject({ symbol: "MSFT" });
    expect(parseScriptAlertCmd(args("TSLA SCRIPT=A"), { symbol: "MSFT" })).toMatchObject({ symbol: "TSLA" });
  });

  it("explains every mistake", () => {
    const msg = (s: string) => {
      const r = parseScriptAlertCmd(args(s));
      return r?.kind === "error" ? r.message : `NOT AN ERROR: ${JSON.stringify(r)}`;
    };
    expect(msg("SCRIPT=A")).toContain("NEEDS A SECURITY");
    expect(msg("AAPL SCRIPT=")).toContain("NEEDS A SCRIPT NAME");
    expect(msg("AAPL SCRIPT=-bad")).toContain("SCRIPT NAME");
    expect(msg('AAPL COND="x y"')).toContain("NEEDS SCRIPT=NAME");
    expect(msg('AAPL SCRIPT=A COND="RSI down')).toContain("CLOSING QUOTE");
    expect(msg('AAPL SCRIPT=A COND=""')).toContain("CONDITION TITLE");
    expect(msg("AAPL SCRIPT=A COND=" + "x".repeat(81))).toContain("AT MOST 80");
    expect(msg("AAPL MSFT SCRIPT=A")).toContain("EXTRA: MSFT");
    expect(msg("AAPL SCRIPT=A COND=up VIA TG")).toContain("NO VIA");
    expect(msg("A$B SCRIPT=A")).toContain("BAD SYMBOL");
  });

  it("reads ALRT DEL SC<id>", () => {
    expect(parseScriptAlertCmd(args("DEL SC3"))).toEqual({ kind: "deleteScript", id: 3 });
    expect(parseScriptAlertCmd(args("rm sc12"))).toEqual({ kind: "deleteScript", id: 12 });
  });
});
