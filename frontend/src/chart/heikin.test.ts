import { describe, expect, it } from "vitest";
import { heikinAshi } from "./heikin";

describe("heikinAshi", () => {
  it("computes the first bar from its own open and close", () => {
    const r = heikinAshi([10], [14], [8], [12]);
    expect(r.c[0]).toBe(11); // (10+14+8+12)/4
    expect(r.o[0]).toBe(11); // (10+12)/2
    expect(r.h[0]).toBe(14);
    expect(r.l[0]).toBe(8);
  });
  it("chains each open from the previous Heikin Ashi bar", () => {
    const r = heikinAshi([10, 12], [14, 16], [8, 11], [12, 15]);
    expect(r.o[1]).toBe(11); // (11+11)/2
    expect(r.c[1]).toBe(13.5); // (12+16+11+15)/4
    expect(r.h[1]).toBe(16);
    expect(r.l[1]).toBe(11);
  });
});
