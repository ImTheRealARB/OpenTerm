import { describe, expect, it } from "vitest";
import { DEFAULTS, normalize } from "../settings/schema";
import { settingsArgs } from "../settings/commands";
import { parseCdepArgs } from "./cryptoArgs";
import { parseFootArgs, parseTasArgs } from "./flowArgs";
import { fmtBytes, parseRecArgs, recordedLabel, sessionId, splitRec, stampOf, stepIndex } from "./recArgs";

const STAMP = "2026-11-24-101500";

describe("REC command words", () => {
  it("lists with no words and starts or stops only when ON / OFF is spelled out", () => {
    expect(parseRecArgs([])).toEqual({ action: "LIST", sym: "" });
    expect(parseRecArgs(["btcusdt", "on"])).toEqual({ action: "ON", sym: "BTCUSDT" });
    expect(parseRecArgs(["BTC-USDT", "OFF"])).toEqual({ action: "OFF", sym: "BTC-USDT" });
  });
  it("never starts a recording from a bare symbol", () => {
    const r = parseRecArgs(["BTCUSDT"]);
    expect(r.action).toBe("LIST");
    expect(r.error).toMatch(/ON \| OFF/);
    expect(parseRecArgs(["ON"]).action).toBe("LIST");
  });
});

describe("REC=<id> token", () => {
  it("is taken out of the words and names the session", () => {
    expect(splitRec(["BTCUSDT", `REC=${STAMP}`])).toEqual({ rest: ["BTCUSDT"], stamp: STAMP, recSym: undefined });
    expect(splitRec([`rec=btcusdt/${STAMP}`]).recSym).toBe("BTCUSDT");
  });
  it("flags a REC= word that is not a session id", () => {
    expect(splitRec(["REC=nope"]).bad).toMatch(/SESSION ID/);
    expect(splitRec(["BTCUSDT"]).bad).toBeUndefined();
  });
  it("builds the server id from the typed symbol (dashes dropped)", () => {
    expect(sessionId("BTC-USDT", STAMP)).toBe(`BTCUSDT/${STAMP}`);
    expect(sessionId("ETHUSDT", STAMP, "BTCUSDT")).toBe(`BTCUSDT/${STAMP}`);
    expect(stampOf(`BTCUSDT/${STAMP}`)).toBe(STAMP);
  });
  it("TAS and FOOT read it and keep their other words", () => {
    const t = parseTasArgs(["BTCUSDT", `REC=${STAMP}`]);
    expect(t).toMatchObject({ sym: "BTCUSDT", rec: `BTCUSDT/${STAMP}` });
    const f = parseFootArgs(["btcusdt", "5m", "40", `rec=${STAMP}`]);
    expect(f).toMatchObject({ sym: "BTCUSDT", interval: "5M", bars: 40, rec: `BTCUSDT/${STAMP}` });
    expect(parseFootArgs(["BTCUSDT", "REC=x"]).recError).toMatch(/SESSION ID/);
  });
  it("TAS and FOOT stay live without it", () => {
    expect(parseTasArgs(["ETHUSDT"]).rec).toBeUndefined();
    expect(parseFootArgs([], "SOLUSDT")).toMatchObject({ sym: "SOLUSDT" });
    expect(parseFootArgs([]).rec).toBeUndefined();
  });
  it("DOM (parseCdepArgs) reads it and still reads the level count", () => {
    expect(parseCdepArgs(["BTCUSDT", "30", `REC=${STAMP}`])).toEqual({ pair: "BTCUSDT", levels: 30, rec: `BTCUSDT/${STAMP}` });
    expect(parseCdepArgs(["BTCUSDT"])).toEqual({ pair: "BTCUSDT", levels: 25 });
    expect(parseCdepArgs(["BTCUSDT", "REC=bad"]).recError).toMatch(/SESSION ID/);
  });
});

describe("REC labels and helpers", () => {
  it("says who recorded it and when", () => {
    expect(recordedLabel(Date.UTC(2026, 10, 24, 10, 15) / 1000)).toBe("RECORDED BY OPENTERM 2026-11-24");
  });
  it("sizes", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(2048)).toBe("2.0 KB");
    expect(fmtBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
  it("steps through DOM snapshots without leaving the range", () => {
    expect(stepIndex(0, -1, 5)).toBe(0);
    expect(stepIndex(4, 1, 5)).toBe(4);
    expect(stepIndex(2, 1, 5)).toBe(3);
    expect(stepIndex(2, -1, 5)).toBe(1);
  });
});

describe("recorder settings", () => {
  it("defaults to 500 MB and 14 days", () => {
    expect(DEFAULTS.recorder).toEqual({ capMb: 500, retentionDays: 14 });
  });
  it("keeps a good value and falls back (with a note) on a bad one", () => {
    expect(normalize({ recorder: { capMb: 200 } }).settings.recorder).toEqual({ capMb: 200, retentionDays: 14 });
    const bad = normalize({ recorder: { capMb: 0, retentionDays: 1.5 } });
    expect(bad.settings.recorder).toEqual({ capMb: 500, retentionDays: 14 });
    expect(bad.errors).toEqual(expect.arrayContaining(["recorder.capMb", "recorder.retentionDays"]));
  });
  it("SETTINGS RECORDER CAP / DAYS", () => {
    const cap = settingsArgs(["RECORDER", "CAP", "250"], DEFAULTS);
    expect(cap).toMatchObject({ ok: true, next: { recorder: { capMb: 250, retentionDays: 14 } } });
    const days = settingsArgs(["RECORDER", "DAYS", "3"], DEFAULTS);
    expect(days).toMatchObject({ ok: true, next: { recorder: { capMb: 500, retentionDays: 3 } } });
    expect(settingsArgs(["RECORDER", "CAP", "0"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["RECORDER", "CAP"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["RECORDER", "ON"], DEFAULTS)).toMatchObject({ ok: false });
  });
});
