import { describe, expect, it } from "vitest";
import { tabParts } from "./tabLabel";

describe("tabParts", () => {
  it("shows the function code as the badge and the ticker as the title", () => {
    expect(tabParts("GP", "AAPL", true, "Price chart")).toEqual({ badge: "GP", title: "AAPL", full: "AAPL GP" });
  });
  it("falls back to the function's plain title when it uses no security", () => {
    expect(tabParts("WEI", "AAPL", false, "World equity indices")).toEqual({ badge: "WEI", title: "World equity indices", full: "WEI" });
  });
  it("ignores a sticky symbol the function does not show", () => {
    expect(tabParts("FRED", "AAPL", false, undefined).full).toBe("FRED");
  });
  it("names an empty panel New tab with no badge", () => {
    expect(tabParts(undefined, undefined, false, undefined)).toEqual({ badge: "", title: "New tab", full: "New tab" });
  });
  it("keeps the badge when the title is unknown", () => {
    expect(tabParts("XYZ", undefined, true, undefined)).toEqual({ badge: "XYZ", title: "", full: "XYZ" });
  });
});
