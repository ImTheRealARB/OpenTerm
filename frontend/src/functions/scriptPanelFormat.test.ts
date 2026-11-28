import { describe, expect, it } from "vitest";
import { describeInput, problemText, summarizeReport, type ImportLine } from "./scriptPanelFormat";

describe("problemText", () => {
  it("says the line and column", () => {
    expect(problemText({ msg: "UNKNOWN NAME FOO", line: 12, col: 5 })).toBe("LINE 12:5 UNKNOWN NAME FOO");
  });
  it("a problem with no position says only the message", () => {
    expect(problemText({ msg: "SOURCE TOO LONG", line: 0, col: 0 })).toBe("SOURCE TOO LONG");
  });
  it("a missing column reads as 1", () => {
    expect(problemText({ msg: "EXPECTED )", line: 3, col: 0 })).toBe("LINE 3:1 EXPECTED )");
  });
});

describe("describeInput", () => {
  it("writes title, kind, default and range", () => {
    expect(describeInput({ title: "Length", type: "int", defval: 14, min: 1, max: 200 })).toBe("Length: int, default 14, 1 to 200");
  });
  it("leaves out what the engine did not give", () => {
    expect(describeInput({ title: "Source" })).toBe("Source");
  });
  it("one-sided ranges and option lists", () => {
    expect(describeInput({ title: "A", min: 2 })).toBe("A: at least 2");
    expect(describeInput({ title: "B", max: 9 })).toBe("B: at most 9");
    expect(describeInput({ title: "C", type: "string", options: ["x", "y"] })).toBe("C: string, one of x, y");
  });
  it("a false default is still shown", () => {
    expect(describeInput({ title: "On", type: "bool", defval: false })).toBe("On: bool, default false");
  });
});

describe("summarizeReport", () => {
  const rep: ImportLine[] = [
    { line: 1, text: "a", status: "ok", note: "" },
    { line: 2, text: "b", status: "ok", note: "" },
    { line: 3, text: "c", status: "changed", note: "varip became var" },
    { line: 4, text: "d", status: "dropped", note: "strategy.entry is not supported" },
  ];
  it("counts kept, changed and dropped lines", () => {
    expect(summarizeReport(rep).headline).toBe("2 LINES KEPT, 1 CHANGED, 1 DROPPED");
  });
  it("lists only the changed and dropped lines, with their notes", () => {
    expect(summarizeReport(rep).lines).toEqual(["LINE 3 CHANGED: varip became var", "LINE 4 DROPPED: strategy.entry is not supported"]);
  });
  it("cuts the list at max and says how many more", () => {
    const many: ImportLine[] = Array.from({ length: 20 }, (_, i) => ({ line: i + 1, text: "x", status: "dropped", note: "n" }));
    const s = summarizeReport(many, 5);
    expect(s.lines).toHaveLength(5);
    expect(s.more).toBe(15);
  });
  it("an empty report is all zeros", () => {
    expect(summarizeReport([])).toEqual({ headline: "0 LINES KEPT, 0 CHANGED, 0 DROPPED", lines: [], more: 0 });
  });
});
