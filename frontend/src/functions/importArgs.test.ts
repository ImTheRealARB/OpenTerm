import { describe, expect, it } from "vitest";
import { looksIntraday } from "../bt/csvImport";
import { parseImportArgs } from "./importArgs";

describe("IMPORT args (Phase 22)", () => {
  it("reads SYNTH with or without spaces, splitting on the first =", () => {
    expect(parseImportArgs(["SYNTH", "PAIR", "=", "AAPL", "/", "MSFT"])).toEqual({ kind: "synth", name: "PAIR", formula: "AAPL / MSFT" });
    expect(parseImportArgs(["synth", "spread=ES=F-NQ=F"])).toEqual({ kind: "synth", name: "SPREAD", formula: "ES=F-NQ=F" });
    expect(parseImportArgs(["SYNTH", "PAIR"]).kind).toBe("error");
  });

  it("keeps the TZ= zone for a paste and the old list / delete forms", () => {
    expect(parseImportArgs(["ES5", "TZ=America/New_York"])).toEqual({ kind: "paste", symbol: "ES5", tz: "America/New_York" });
    expect(parseImportArgs([])).toEqual({ kind: "list" });
    expect(parseImportArgs(["DEL", "abc"])).toEqual({ kind: "list", del: "ABC" });
  });
});

describe("intraday CSV detection", () => {
  it("needs a repeated date AND a time", () => {
    expect(looksIntraday(["2026-01-02 09:30", "2026-01-02 09:35"])).toBe(true);
    expect(looksIntraday(["2026-01-02 16:00", "2026-01-05 16:00"])).toBe(false); // daily with times: stays daily
    expect(looksIntraday(["2026-01-02", "2026-01-02"])).toBe(false); // a duplicate daily date: the daily check reports it
  });
});
