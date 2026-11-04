import { describe, expect, it } from "vitest";
import { IDLE, NUM_MAX_DIGITS, NUM_TTL_MS, isLive, keysToRow, numberSelectKey } from "./numberSelect";

describe("numberSelectKey", () => {
  it("digits then Enter open that row", () => {
    const a = numberSelectKey(IDLE, "3", 0, true);
    expect(a).toMatchObject({ kind: "digit", state: { buf: "3" } });
    const b = numberSelectKey(a.state, "Enter", 100, true);
    expect(b).toMatchObject({ kind: "open", n: 3 });
    expect(b.state.buf).toBe("");
  });
  it("collects several digits, capped", () => {
    let s = IDLE;
    for (const k of "12") s = numberSelectKey(s, k, 0, true).state;
    expect(numberSelectKey(s, "Enter", 1, true)).toMatchObject({ kind: "open", n: 12 });
    s = IDLE;
    for (const k of "123456") s = numberSelectKey(s, k, 0, true).state;
    expect(s.buf).toHaveLength(NUM_MAX_DIGITS);
  });
  it("does not start without a grid, on 0, or for other keys", () => {
    expect(numberSelectKey(IDLE, "3", 0, false).kind).toBe("pass");
    expect(numberSelectKey(IDLE, "0", 0, true).kind).toBe("pass");
    expect(numberSelectKey(IDLE, "j", 0, true).kind).toBe("pass");
    expect(numberSelectKey(IDLE, "Enter", 0, true).kind).toBe("pass");
  });
  it("expires", () => {
    const a = numberSelectKey(IDLE, "3", 0, true).state;
    expect(isLive(a, NUM_TTL_MS)).toBe(true);
    expect(isLive(a, NUM_TTL_MS + 1)).toBe(false);
    expect(numberSelectKey(a, "Enter", NUM_TTL_MS + 1, true).kind).toBe("pass");
  });
  it("colon hands the digits to the command line (3:GP)", () => {
    const a = numberSelectKey(IDLE, "3", 0, true).state;
    expect(numberSelectKey(a, ":", 1, true)).toMatchObject({ kind: "flush", text: "3" });
    expect(numberSelectKey(a, "Shift", 1, true).kind).toBe("pass");
    expect(numberSelectKey(a, "Shift", 1, true).state.buf).toBe("3");
  });
  it("Escape, Backspace and other keys drop it", () => {
    const a = numberSelectKey(IDLE, "3", 0, true).state;
    expect(numberSelectKey(a, "Escape", 1, true)).toMatchObject({ kind: "clear", swallow: true });
    expect(numberSelectKey(a, "Backspace", 1, true)).toMatchObject({ kind: "clear", swallow: true });
    expect(numberSelectKey(a, "j", 1, true)).toMatchObject({ kind: "clear", swallow: false });
    const b = numberSelectKey(numberSelectKey(IDLE, "1", 0, true).state, "2", 0, true).state;
    expect(numberSelectKey(b, "Backspace", 1, true)).toMatchObject({ kind: "digit", state: { buf: "1" } });
  });
  it("keysToRow", () => {
    expect(keysToRow(1)).toEqual(["Home"]);
    expect(keysToRow(3)).toEqual(["Home", "ArrowDown", "ArrowDown"]);
  });
});
