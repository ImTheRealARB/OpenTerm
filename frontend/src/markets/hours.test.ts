import { describe, expect, it } from "vitest";
import { MARKETS, isOpen } from "./hours";

const ny = MARKETS.find((m) => m.code === "NY")!;
const tk = MARKETS.find((m) => m.code === "TK")!;

describe("market hours", () => {
  it("NYSE open midday Wednesday, closed weekend", () => {
    expect(isOpen(ny, new Date("2026-10-14T16:00:00Z"))).toBe(true); // 12:00 ET
    expect(isOpen(ny, new Date("2026-10-14T21:00:00Z"))).toBe(false); // 17:00 ET
    expect(isOpen(ny, new Date("2026-10-17T16:00:00Z"))).toBe(false); // Saturday
  });
  it("Tokyo lunch break is closed", () => {
    expect(isOpen(tk, new Date("2026-10-14T03:00:00Z"))).toBe(false); // 12:00 JST
    expect(isOpen(tk, new Date("2026-10-14T01:00:00Z"))).toBe(true); // 10:00 JST
  });
});
