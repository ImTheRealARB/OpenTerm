import { describe, expect, it } from "vitest";
import { aiArgs } from "./aiArgs";

describe("aiArgs", () => {
  it("no args opens an empty chat; words are one question", () => {
    expect(aiArgs([])).toEqual({ mode: "ask", text: "" });
    expect(aiArgs(["what", "is", "AAPL", "doing?"])).toEqual({ mode: "ask", text: "what is AAPL doing?" });
  });
  it("BT drafts a strategy from the rest of the line", () => {
    expect(aiArgs(["BT", "buy", "AAPL", "on", "a", "20/50", "cross"])).toEqual({ mode: "bt", text: "buy AAPL on a 20/50 cross" });
    expect(aiArgs(["bt"])).toEqual({ mode: "bad", text: "", error: "USAGE: AI BT <strategy idea in words>" });
  });
  it("CHART describes the open chart, optionally with a hint", () => {
    expect(aiArgs(["CHART"])).toEqual({ mode: "chart", text: "" });
    expect(aiArgs(["chart", "support", "levels"])).toEqual({ mode: "chart", text: "support levels" });
  });
  it("only the first word picks a mode: a question that mentions BT is still a question", () => {
    expect(aiArgs(["why", "BT", "failed"])).toEqual({ mode: "ask", text: "why BT failed" });
  });
});
