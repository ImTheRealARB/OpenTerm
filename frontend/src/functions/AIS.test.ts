import { describe, expect, it } from "vitest";
import { AIS_AREAS, aisQuery, fmtAge, fmtDegrees, fmtFrom, fmtKnots, fmtLatLon, listeningText, memoryNote, quietText, stepArea } from "./aisArgs";
import { FUNCTIONS } from "./registry";

describe("AIS registry entry", () => {
  it("is registered with a loader", () => {
    const def = FUNCTIONS.get("AIS");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
  });
});

describe("aisQuery", () => {
  it("defaults to the first chokepoint and upper-cases what is typed", () => {
    expect(aisQuery([])).toBe("SUEZ");
    expect(aisQuery(["hormuz"])).toBe("HORMUZ");
    expect(aisQuery(["box", "25.6", "-80.2", "25.8", "-79.9"])).toBe("BOX 25.6 -80.2 25.8 -79.9");
  });
});

describe("stepArea", () => {
  it("cycles through the presets both ways and leaves a custom box at either end", () => {
    expect(stepArea("SUEZ", 1)).toBe(AIS_AREAS[1]);
    expect(stepArea("SUEZ", -1)).toBe(AIS_AREAS[AIS_AREAS.length - 1]);
    expect(stepArea(AIS_AREAS[AIS_AREAS.length - 1], 1)).toBe("SUEZ");
    expect(stepArea("BOX 1 2 3 4", 1)).toBe("SUEZ");
    expect(stepArea("BOX 1 2 3 4", -1)).toBe(AIS_AREAS[AIS_AREAS.length - 1]);
  });
});

describe("AIS formatting", () => {
  it("shows a missing speed or course as blank, never as zero", () => {
    expect(fmtKnots(null)).toBe("");
    expect(fmtKnots(0)).toBe("0.0");
    expect(fmtKnots(12.34)).toBe("12.3");
    expect(fmtDegrees(null)).toBe("");
    expect(fmtDegrees(359.6)).toBe("0");
    expect(fmtDegrees(86.7)).toBe("87");
  });
  it("formats a position with hemispheres", () => {
    expect(fmtLatLon(30.2, 32.55)).toBe("30.200N 32.550E");
    expect(fmtLatLon(-33.9, -18.4)).toBe("33.900S 18.400W");
  });
  it("formats ages", () => {
    expect([fmtAge(null), fmtAge(12), fmtAge(300), fmtAge(7200), fmtAge(400000)]).toEqual(["", "12S", "5M", "2H", "5D"]);
  });
  it("labels remembered rows honestly and promises the real listen time", () => {
    expect(fmtFrom(true)).toBe("MEMORY");
    expect(fmtFrom(false)).toBe("LIVE");
    expect(memoryNote()).toContain("POSITIONS UP TO 5 MIN OLD FROM EARLIER LISTENS");
    expect(memoryNote(120)).toContain("UP TO 2 MIN OLD");
    expect(listeningText()).toBe("LISTENING FOR ABOUT 15 SECONDS…");
  });
  it("says a quiet listen does not prove the area is empty", () => {
    expect(quietText(8, 0)).toContain("DOES NOT SHOW THE AREA IS EMPTY");
  });
});
