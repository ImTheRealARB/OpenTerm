import { describe, expect, it } from "vitest";
import { parseFieldTimes, parseMirror, sameMirror } from "./mirror";

describe("parseMirror (another tab's localStorage value)", () => {
  it("reads a well-formed mirror", () => {
    expect(parseMirror(JSON.stringify({ settings: { theme: "amber" }, updatedAt: 12, dirty: true }))).toEqual({ settings: { theme: "amber" }, updatedAt: 12, dirty: true });
  });
  it("defaults a missing time and flag", () => {
    expect(parseMirror(JSON.stringify({ settings: {} }))).toEqual({ settings: {}, updatedAt: 0, dirty: false });
  });
  it("reads per-field times, and treats a missing or malformed map as a legacy mirror (undefined)", () => {
    expect(parseMirror(JSON.stringify({ settings: {}, fieldTimes: { theme: 5, vim: 0 } }))?.fieldTimes).toEqual({ theme: 5, vim: 0 });
    expect(parseMirror(JSON.stringify({ settings: {}, fieldTimes: { theme: "x", vim: -1, font: 3 } }))?.fieldTimes).toEqual({ font: 3 });
    expect(parseMirror(JSON.stringify({ settings: {} }))?.fieldTimes).toBeUndefined();
    expect(parseMirror(JSON.stringify({ settings: {}, fieldTimes: [1] }))?.fieldTimes).toBeUndefined();
    expect(parseFieldTimes("nope")).toBeUndefined();
  });
  it("ignores a removed key, broken JSON and values that are not mirrors", () => {
    expect(parseMirror(null)).toBeNull();
    expect(parseMirror("")).toBeNull();
    expect(parseMirror("{not json")).toBeNull();
    expect(parseMirror("42")).toBeNull();
    expect(parseMirror("[]")).toBeNull();
    expect(parseMirror(JSON.stringify({ updatedAt: 1 }))).toBeNull();
    expect(parseMirror(JSON.stringify({ settings: [1] }))).toBeNull();
  });
});

describe("sameMirror (no echo when nothing changed)", () => {
  const a = { settings: { theme: "amber" as const }, updatedAt: 1, dirty: false };
  it("is true for equal content", () => {
    expect(sameMirror(a, { settings: { theme: "amber" as const }, updatedAt: 1, dirty: false })).toBe(true);
  });
  it("is false when settings, time or dirty differ", () => {
    expect(sameMirror(a, { ...a, settings: { theme: "white" } })).toBe(false);
    expect(sameMirror(a, { ...a, updatedAt: 2 })).toBe(false);
    expect(sameMirror(a, { ...a, dirty: true })).toBe(false);
    expect(sameMirror(a, { ...a, fieldTimes: { theme: 1 } })).toBe(false);
  });
});
