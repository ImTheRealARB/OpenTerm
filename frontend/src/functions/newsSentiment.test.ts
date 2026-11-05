import { describe, expect, it } from "vitest";
import { sentimentClass, sentimentText } from "./newsSentiment";

describe("N sentiment line", () => {
  it("says whose score it is and what range it is in", () => {
    expect(sentimentText(0.5)).toBe("SENTIMENT +0.50 POSITIVE (MARKETAUX SCORE, -1 TO +1)");
    expect(sentimentText(-0.25)).toBe("SENTIMENT -0.25 NEGATIVE (MARKETAUX SCORE, -1 TO +1)");
    expect(sentimentText(0.01)).toContain("NEUTRAL");
  });

  it("shows nothing when the source gave no score", () => {
    expect(sentimentText(null)).toBe("");
    expect(sentimentText(undefined)).toBe("");
    expect(sentimentText(Number.NaN)).toBe("");
  });

  it("colours only clearly positive or negative scores", () => {
    expect(sentimentClass(0.5)).toBe("up");
    expect(sentimentClass(-0.5)).toBe("down");
    expect(sentimentClass(0.02)).toBe("dim");
    expect(sentimentClass(null)).toBe("dim");
  });
});
