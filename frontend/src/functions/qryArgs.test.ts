import { describe, expect, it } from "vitest";
import { qryText } from "./qryArgs";

describe("qryText", () => {
  it("joins the split command back into one query", () => {
    expect(qryText(["last,", "pe", "FOR", "SPX", "WHERE", "pe<20"])).toBe("QRY last, pe FOR SPX WHERE pe<20");
  });
  it("is null with no arguments (the panel shows the usage)", () => {
    expect(qryText([])).toBeNull();
    expect(qryText(["  "])).toBeNull();
  });
});
