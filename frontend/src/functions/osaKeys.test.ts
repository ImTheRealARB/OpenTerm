import { describe, expect, it } from "vitest";
import { stepArg } from "./osaKeys";

describe("stepArg", () => {
  it("adds, steps and floors a KEY=number argument", () => {
    expect(stepArg(["LEGS=+1C270"], "DAYS", 7, 0)).toEqual(["LEGS=+1C270", "DAYS=7"]);
    expect(stepArg(["DAYS=7", "X=1"], "DAYS", -14, 0)).toEqual(["DAYS=0", "X=1"]);
    expect(stepArg(["ivshift=-5"], "IVSHIFT", -5, -95)).toEqual(["IVSHIFT=-10"]);
  });
});
