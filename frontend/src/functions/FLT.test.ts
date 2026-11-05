import { describe, expect, it } from "vitest";
import { creditsText, FLT_AREAS, fltQuery, fmtAge, fmtFeet, fmtHeading, fmtKt, fmtLatLon, fmtVrate, quietText, stepArea } from "./fltArgs";
import { FUNCTIONS } from "./registry";

describe("FLT registry entry", () => {
  it("is registered with a loader and needs no security", () => {
    const def = FUNCTIONS.get("FLT");
    expect(def?.load).toBeTypeOf("function");
    expect(def?.needsSecurity).toBe(false);
  });
});

describe("fltQuery", () => {
  it("defaults to the first city and upper-cases what is typed", () => {
    expect(fltQuery([])).toBe("LONDON");
    expect(fltQuery(["dubai"])).toBe("DUBAI");
    expect(fltQuery(["box", "51", "-1", "52", "1"])).toBe("BOX 51 -1 52 1");
    expect(fltQuery(["callsign", "baw"])).toBe("CALLSIGN BAW");
  });
});

describe("stepArea", () => {
  it("cycles through the cities both ways and leaves a box or callsign search at either end", () => {
    expect(stepArea("LONDON", 1)).toBe(FLT_AREAS[1]);
    expect(stepArea("LONDON", -1)).toBe(FLT_AREAS[FLT_AREAS.length - 1]);
    expect(stepArea(FLT_AREAS[FLT_AREAS.length - 1], 1)).toBe("LONDON");
    expect(stepArea("CALLSIGN BAW", 1)).toBe("LONDON");
    expect(stepArea("BOX 1 2 3 4", -1)).toBe(FLT_AREAS[FLT_AREAS.length - 1]);
  });
});

describe("FLT formatting", () => {
  it("shows a missing value as blank, never as zero", () => {
    expect(fmtFeet(null)).toBe("");
    expect(fmtFeet(0)).toBe("0");
    expect(fmtFeet(35000)).toBe("35,000");
    expect(fmtKt(null)).toBe("");
    expect(fmtKt(250)).toBe("250");
    expect(fmtHeading(null)).toBe("");
    expect(fmtHeading(95)).toBe("095");
    expect(fmtVrate(null)).toBe("");
    expect(fmtVrate(0)).toBe("0");
    expect(fmtVrate(1200)).toBe("+1,200");
    expect(fmtVrate(-800)).toBe("-800");
  });
  it("formats a position and an age", () => {
    expect(fmtLatLon(51.52, -0.12)).toBe("51.520N 0.120W");
    expect(fmtAge(null)).toBe("");
    expect(fmtAge(20)).toBe("20S");
    expect(fmtAge(300)).toBe("5M");
    expect(fmtAge(7200)).toBe("2H");
  });
  it("says what the call cost and never invents a missing balance", () => {
    expect(creditsText(1, 397)).toBe("THIS CALL COST 1 CREDIT · 397 CREDITS LEFT");
    expect(creditsText(4, null)).toBe("THIS CALL COST 4 CREDITS · REMAINING CREDITS NOT REPORTED");
  });
  it("does not claim an empty sky", () => {
    expect(quietText(0)).toContain("DOES NOT MEAN THE SKY IS EMPTY");
    expect(quietText(3)).toContain("3 AIRCRAFT WERE HEARD BUT NONE HAS A POSITION");
  });
});
