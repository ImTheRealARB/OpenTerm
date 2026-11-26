import { describe, expect, it } from "vitest";
import { browserChecksNews } from "./newsAlertGate";

describe("browserChecksNews", () => {
  it("is true only in fixture mode", () => {
    expect(browserChecksNews({ fixtures: true })).toBe(true);
    expect(browserChecksNews({ fixtures: false })).toBe(false);
    expect(browserChecksNews({})).toBe(false);
    expect(browserChecksNews(null)).toBe(false);
    expect(browserChecksNews(undefined)).toBe(false);
  });
});
