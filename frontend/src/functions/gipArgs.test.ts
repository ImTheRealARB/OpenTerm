import { describe, expect, it } from "vitest";
import { gipApiBar, nextGipBar, parseGipArgs } from "./gipArgs";

describe("GIP arguments", () => {
  it("bar size, default 5S", () => {
    expect(parseGipArgs([])).toEqual({ bar: "5S" });
    expect(parseGipArgs(["1s"])).toEqual({ bar: "1S" });
    expect(parseGipArgs(["15S"])).toEqual({ bar: "15S" });
    expect(parseGipArgs(["1MIN"])).toEqual({ bar: "1M" });
    expect(parseGipArgs(["nonsense"])).toEqual({ bar: "5S" });
  });
  it("API value and cycling", () => {
    expect(gipApiBar("15S")).toBe("15s");
    expect(gipApiBar("1M")).toBe("1m");
    expect(["1S", "5S", "15S", "1M"].map((b) => nextGipBar(b as "1S"))).toEqual(["5S", "15S", "1M", "1S"]);
  });
});
