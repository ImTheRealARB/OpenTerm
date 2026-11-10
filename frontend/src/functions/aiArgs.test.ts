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
  it("DOC loads a filing, switches the document off, or waits for an upload", () => {
    expect(aiArgs(["DOC"])).toEqual({ mode: "doc", text: "" });
    expect(aiArgs(["doc", "filing", "aapl"])).toEqual({ mode: "docfiling", text: "", symbol: "AAPL", form: "10-K" });
    expect(aiArgs(["DOC", "FILING", "msft", "10-q"])).toEqual({ mode: "docfiling", text: "", symbol: "MSFT", form: "10-Q" });
    expect(aiArgs(["DOC", "OFF"])).toEqual({ mode: "docoff", text: "" });
    expect(aiArgs(["DOC", "FILING"])).toEqual({ mode: "bad", text: "", error: "USAGE: AI DOC [FILING <SYMBOL> [FORM]] | AI DOC OFF (U uploads a file)" });
    expect(aiArgs(["DOC", "what"])).toMatchObject({ mode: "bad" });
  });
  it("only the first word picks a mode: a question that mentions BT is still a question", () => {
    expect(aiArgs(["why", "BT", "failed"])).toEqual({ mode: "ask", text: "why BT failed" });
  });
});

describe("aiArgs AUTO", () => {
  it("AUTO tests a hypothesis from the rest of the line", () => {
    expect(aiArgs(["AUTO", "momentum", "works", "on", "AAPL"])).toEqual({ mode: "auto", text: "momentum works on AAPL" });
    expect(aiArgs(["auto"]).mode).toBe("bad");
  });
});

describe("aiArgs FILING", () => {
  it("asks a question about the newest 10-K or 10-Q, or names the form", () => {
    expect(aiArgs(["FILING", "aapl", "what", "are", "the", "supply", "risks?"])).toEqual({ mode: "filing", text: "what are the supply risks?", symbol: "AAPL", form: null, drivers: false });
    expect(aiArgs(["filing", "msft", "10-q", "capex", "plans"])).toEqual({ mode: "filing", text: "capex plans", symbol: "MSFT", form: "10-Q", drivers: false });
  });
  it("DRIVERS is its own request, only when it is the whole question", () => {
    expect(aiArgs(["FILING", "AAPL", "DRIVERS"])).toEqual({ mode: "filing", text: "DRIVERS", symbol: "AAPL", form: null, drivers: true });
    expect(aiArgs(["FILING", "AAPL", "10-K", "drivers"])).toMatchObject({ mode: "filing", form: "10-K", drivers: true });
    expect(aiArgs(["FILING", "AAPL", "what", "drivers", "margins"])).toMatchObject({ mode: "filing", drivers: false, text: "what drivers margins" });
  });
  it("GUIDANCE and CHAIN are presets like DRIVERS, only when they are the whole question", () => {
    expect(aiArgs(["FILING", "aapl", "guidance"])).toEqual({ mode: "filing", text: "GUIDANCE", symbol: "AAPL", form: null, drivers: false, preset: "guidance" });
    expect(aiArgs(["FILING", "AAPL", "10-Q", "chain"])).toMatchObject({ mode: "filing", form: "10-Q", preset: "chain", drivers: false });
    expect(aiArgs(["FILING", "AAPL", "supply", "chain"])).toEqual({ mode: "filing", text: "supply chain", symbol: "AAPL", form: null, drivers: false });
    expect(aiArgs(["FILING", "AAPL", "guidance", "for", "capex"])).not.toHaveProperty("preset");
  });
  it("a missing symbol or question is a usage error, and AI DOC FILING is untouched", () => {
    expect(aiArgs(["FILING"]).mode).toBe("bad");
    expect(aiArgs(["FILING", "AAPL"]).mode).toBe("bad");
    expect(aiArgs(["FILING", "AAPL", "10-K"]).mode).toBe("bad");
    expect(aiArgs(["FILING", "bad symbol!", "x"]).mode).toBe("bad");
    expect(aiArgs(["DOC", "FILING", "aapl"])).toMatchObject({ mode: "docfiling", symbol: "AAPL" });
    expect(aiArgs(["what", "FILING", "says"])).toEqual({ mode: "ask", text: "what FILING says" });
  });
});

describe("aiArgs BT CODE", () => {
  it("BT CODE drafts a Python strategy from the rest of the line", () => {
    expect(aiArgs(["BT", "CODE", "buy", "dips"])).toEqual({ mode: "btcode", text: "buy dips" });
    expect(aiArgs(["bt", "code", "RSI", "dip"])).toEqual({ mode: "btcode", text: "RSI dip" });
    expect(aiArgs(["BT", "CODE"])).toEqual({ mode: "bad", text: "", error: "USAGE: AI BT CODE <strategy idea in words>" });
  });
  it("a plain BT idea that merely contains the word code stays a rule draft", () => {
    expect(aiArgs(["BT", "buy", "code", "stocks"])).toEqual({ mode: "bt", text: "buy code stocks" });
  });
});
