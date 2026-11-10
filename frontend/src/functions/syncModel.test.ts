import { describe, expect, it } from "vitest";
import type { SyncRecord } from "../net/syncApi";
import { FUNCTIONS } from "./registry";
import { ageText, countsLine, diffLines, headline, noDifference, parseSyncArgs, STALE_AFTER_S } from "./syncModel";

// Records below are TEST DATA written for these tests (NOT a recording of any broker).
const rec = (over: Partial<SyncRecord> = {}): SyncRecord => ({
  broker: "kite", portfolio: "KITE", at: 1_000_000, ok: true, error: null, base: "INR",
  counts: { fetched: 5, imported: 4, skipped: 1, conflicts: 0, manual_kept: 2, previous: 3 },
  diff: { added: ["TCS.NS"], removed: ["OLD.NS"], changed: [{ symbol: "INFY.NS", qty_from: 10, qty_to: 4, cost_from: 1400.5, cost_to: 1400.5 }] },
  skipped: [], conflicts: [], warnings: [], holdings: 4, positions: 0, ...over,
});

describe("SYNC registry entry", () => {
  it("is registered, lazy, and takes no security", () => {
    const f = FUNCTIONS.get("SYNC");
    expect(f?.load).toBeTypeOf("function");
    expect(f?.needsSecurity).toBe(false);
  });
});

describe("parseSyncArgs", () => {
  it("reads broker, portfolio and flags in any order", () => {
    expect(parseSyncArgs(["kite", "main", "pos", "go"])).toEqual({ broker: "kite", portfolio: "MAIN", positions: true, account: null, go: true });
    expect(parseSyncArgs(["IBKR", "acct=U1234567"])).toMatchObject({ broker: "ibkr", account: "U1234567", go: false });
    expect(parseSyncArgs([])).toMatchObject({ broker: null, portfolio: null });
  });
  it("refuses what cannot work", () => {
    expect(parseSyncArgs(["go"])).toHaveProperty("error");
    expect(parseSyncArgs(["kite", "ibkr"])).toHaveProperty("error");
    expect(parseSyncArgs(["ibkr", "pos"])).toHaveProperty("error");
    expect(parseSyncArgs(["kite", "acct=U1234567"])).toHaveProperty("error");
    expect(parseSyncArgs(["kite", "bad name!"])).toHaveProperty("error");
    expect(parseSyncArgs(["ibkr", "acct=x"])).toHaveProperty("error");
  });
});

describe("ageText", () => {
  it("rounds down to the largest unit", () => {
    expect(ageText(100, 130)).toBe("JUST NOW");
    expect(ageText(0, 300)).toBe("5M AGO");
    expect(ageText(0, 7300)).toBe("2H AGO");
    expect(ageText(0, 3 * 86400 + 5)).toBe("3D AGO");
  });
});

describe("diff and counts lines", () => {
  it("lists added, removed and changed symbols", () => {
    expect(diffLines(rec().diff)).toEqual(["+ TCS.NS", "- OLD.NS", "~ INFY.NS 10 -> 4"]);
    expect(diffLines({ added: [], removed: [], changed: [{ symbol: "A", qty_from: 1, qty_to: 1, cost_from: 5, cost_to: null }] })).toEqual(["~ A 1 -> 1 (COST 5 -> -)"]);
    expect(diffLines(null)).toEqual([]);
  });
  it("caps long diffs", () => {
    const added = Array.from({ length: 40 }, (_, i) => `S${i}`);
    const lines = diffLines({ added, removed: [], changed: [] }, 30);
    expect(lines).toHaveLength(31);
    expect(lines[30]).toBe("… 10 MORE");
  });
  it("knows an empty difference", () => {
    expect(noDifference({ added: [], removed: [], changed: [] })).toBe(true);
    expect(noDifference(rec().diff)).toBe(false);
    expect(noDifference(null)).toBe(false);
  });
  it("summarises counts per broker", () => {
    expect(countsLine(rec())).toBe("4 LOTS IMPORTED · 1 SKIPPED · 0 CONFLICTS · 2 MANUAL KEPT · 4 HOLDINGS · 0 POSITIONS");
    expect(countsLine(rec({ broker: "ibkr", accounts: ["U1", "U2"] }))).toContain("2 ACCOUNTS");
  });
});

describe("headline", () => {
  const ok = rec();
  it("shows source, portfolio and age for a fresh sync", () => {
    const h = headline("kite", ok, null, ok.at + 120);
    expect(h.cls).toBe("up");
    expect(h.text).toContain("KITE → KITE");
    expect(h.text).toContain("2M AGO");
  });
  it("says STALE after a day", () => {
    expect(headline("kite", ok, null, ok.at + STALE_AFTER_S + 1)).toMatchObject({ cls: "warn" });
    expect(headline("kite", ok, null, ok.at + STALE_AFTER_S + 1).text.startsWith("STALE")).toBe(true);
  });
  it("says ERR when a later try failed, and when it never worked", () => {
    const bad = rec({ ok: false, at: ok.at + 60, error: "IBKR GATEWAY NOT RUNNING" });
    expect(headline("kite", ok, bad, ok.at + 120).text.startsWith("ERR")).toBe(true);
    expect(headline("ibkr", null, bad, ok.at + 120)).toMatchObject({ cls: "err" });
    expect(headline("ibkr", null, null, 0)).toEqual({ text: "IBKR NEVER SYNCED", cls: "dim" });
  });
});
