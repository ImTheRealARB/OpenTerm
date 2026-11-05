import { describe, expect, it } from "vitest";
import { parseMapArgs } from "./mapArgs";

describe("parseMapArgs", () => {
  it("bare MAP = default layers, no area", () => {
    expect(parseMapArgs([])).toEqual({ layers: null, area: null, error: null });
  });
  it("names layers, with aliases", () => {
    expect(parseMapArgs(["vessels", "ports"]).layers).toEqual(["vessels", "ports"]);
    expect(parseMapArgs(["ships", "EQ", "straits"]).layers).toEqual(["vessels", "quakes", "chokepoints"]);
    expect(parseMapArgs(["VESSELS", "vessels"]).layers).toEqual(["vessels"]);
  });
  it("a chokepoint name is an area to centre on", () => {
    expect(parseMapArgs(["VESSELS", "HORMUZ"])).toEqual({ layers: ["vessels"], area: "HORMUZ", error: null });
    expect(parseMapArgs(["hormuz"])).toEqual({ layers: null, area: "HORMUZ", error: null });
  });
  it("an unknown word is a usage error, never silently ignored", () => {
    const r = parseMapArgs(["VESSELS", "NARNIA"]);
    expect(r.error).toMatch(/^USAGE: MAP/);
    expect(r.error).toContain("NARNIA");
  });
  it("two areas are an error too", () => {
    expect(parseMapArgs(["SUEZ", "HORMUZ"]).error).toMatch(/ONE AREA/);
  });
});
