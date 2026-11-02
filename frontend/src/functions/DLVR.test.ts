import { describe, expect, it } from "vitest";
import { briefStamp, fieldError, fieldPatch, fieldValue, sectionMeta } from "./dlvrFields";
import { FUNCTIONS } from "./registry";

describe("DLVR / BRIEF registry entries", () => {
  it("are registered with a loader", () => {
    for (const code of ["DLVR", "BRIEF"]) expect(FUNCTIONS.get(code)?.load).toBeTypeOf("function");
  });
});

describe("fieldError", () => {
  it("accepts one email and the empty string, rejects lists", () => {
    expect(fieldError("email_to", "me@example.com")).toBeNull();
    expect(fieldError("email_to", "")).toBeNull();
    expect(fieldError("email_to", "a@b.com, c@d.com")).not.toBeNull();
    expect(fieldError("email_to", "nope")).not.toBeNull();
  });
  it("checks telegram chat ids", () => {
    expect(fieldError("telegram_chat_id", "-100123")).toBeNull();
    expect(fieldError("telegram_chat_id", "@mychannel")).toBeNull();
    expect(fieldError("telegram_chat_id", "@ab")).not.toBeNull();
  });
  it("checks brief time and days", () => {
    expect(fieldError("brief.time", "08:30")).toBeNull();
    expect(fieldError("brief.time", "8:30")).not.toBeNull();
    expect(fieldError("brief.time", "24:00")).not.toBeNull();
    expect(fieldError("brief.days", "daily")).toBeNull();
    expect(fieldError("brief.days", "weekends")).not.toBeNull();
    expect(fieldError("brief.tz", "")).toBeNull();
  });
});

describe("fieldPatch / fieldValue", () => {
  it("builds flat and nested patches", () => {
    expect(fieldPatch("email_to", " a@b.co ")).toEqual({ email_to: "a@b.co" });
    expect(fieldPatch("brief.time", "09:00")).toEqual({ brief: { time: "09:00" } });
  });
  it("reads values back", () => {
    const s = { channels: { email: false, telegram: false, webhook: false, desktop: false }, email_to: "x@y.zz", telegram_chat_id: "", brief: { enabled: false, time: "08:30", days: "mon-fri", tz: "" } };
    expect(fieldValue(s, "email_to")).toBe("x@y.zz");
    expect(fieldValue(s, "brief.days")).toBe("mon-fri");
  });
});

describe("sectionMeta", () => {
  const age = (s: number) => `${s}S`;
  const base = { id: "a", title: "A", source: "yahoo", age_s: 5, stale: false, error: null, lines: [] };
  it("shows source and age, STALE, or the error", () => {
    expect(sectionMeta(base, age)).toEqual({ text: "YAHOO · 5S", cls: "dim" });
    expect(sectionMeta({ ...base, stale: true }, age).cls).toBe("warn");
    expect(sectionMeta({ ...base, error: "boom" }, age)).toEqual({ text: "ERR: boom", cls: "err" });
  });
});

describe("briefStamp", () => {
  it("formats as YYYY-MM-DD HH:MM", () => {
    expect(briefStamp(0)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
  });
});
