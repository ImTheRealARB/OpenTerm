import { describe, expect, it } from "vitest";
import { DEFAULTS, TAPE_DEFAULT, TAPE_MAX, type Settings } from "../settings/schema";
import { tapeCommand } from "./tapeArgs";

const withList = (tapeSymbols: string[]): Settings => ({ ...DEFAULTS, tapeSymbols });

describe("TAPE", () => {
  it("bare TAPE lists the symbols and changes nothing", () => {
    const r = tapeCommand([], DEFAULTS);
    expect(r).toMatchObject({ ok: true });
    if (r.ok) {
      expect(r.next).toBe(DEFAULTS);
      expect(r.message).toContain("^GSPC");
    }
    expect(tapeCommand([], withList([]))).toMatchObject({ ok: true, message: expect.stringContaining("EMPTY") });
  });

  it("ADD appends an upper-cased symbol, with a market word for suffixes", () => {
    expect(tapeCommand(["ADD", "aapl"], withList(["^GSPC"]))).toMatchObject({ ok: true, next: { tapeSymbols: ["^GSPC", "AAPL"] } });
    expect(tapeCommand(["add", "reliance", "ns"], withList([]))).toMatchObject({ ok: true, next: { tapeSymbols: ["RELIANCE.NS"] } });
    expect(tapeCommand(["ADD", "BTC-USD"], withList([]))).toMatchObject({ ok: true, next: { tapeSymbols: ["BTC-USD"] } });
  });

  it("ADD refuses repeats, bad symbols, unknown market words and a full tape", () => {
    expect(tapeCommand(["ADD", "AAPL"], withList(["AAPL"]))).toMatchObject({ ok: false });
    expect(tapeCommand(["ADD"], DEFAULTS)).toMatchObject({ ok: false });
    expect(tapeCommand(["ADD", "$$"], DEFAULTS)).toMatchObject({ ok: false });
    expect(tapeCommand(["ADD", "AAPL", "MARS"], DEFAULTS)).toMatchObject({ ok: false });
    const full = withList(Array.from({ length: TAPE_MAX }, (_, i) => `S${i}`));
    expect(tapeCommand(["ADD", "AAPL"], full)).toMatchObject({ ok: false });
  });

  it("DEL removes one, and says so when it is not there", () => {
    expect(tapeCommand(["DEL", "aapl"], withList(["AAPL", "MSFT"]))).toMatchObject({ ok: true, next: { tapeSymbols: ["MSFT"] } });
    expect(tapeCommand(["DEL", "NOPE"], withList(["AAPL"]))).toMatchObject({ ok: false });
    expect(tapeCommand(["DEL"], DEFAULTS)).toMatchObject({ ok: false });
  });

  it("RESET restores the defaults; ON / OFF flip the top-bar setting only", () => {
    expect(tapeCommand(["RESET"], withList([]))).toMatchObject({ ok: true, next: { tapeSymbols: [...TAPE_DEFAULT] } });
    expect(tapeCommand(["on"], DEFAULTS)).toMatchObject({ ok: true, next: { tape: true } });
    expect(tapeCommand(["OFF"], { ...DEFAULTS, tape: true })).toMatchObject({ ok: true, next: { tape: false } });
    expect(tapeCommand(["WAT"], DEFAULTS)).toMatchObject({ ok: false });
  });
});
