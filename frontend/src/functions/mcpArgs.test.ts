import { describe, expect, it } from "vitest";
import { enableStep, mcpArgs, withTool } from "./mcpArgs";

describe("MCP args", () => {
  it("lists with no args", () => expect(mcpArgs([])).toEqual({ mode: "list" }));
  it("enable needs YES to be confirmed", () => {
    expect(mcpArgs(["ENABLE", "nse-mcp"])).toEqual({ mode: "enable", name: "nse-mcp", confirmed: false });
    expect(mcpArgs(["enable", "nse-mcp", "yes"])).toEqual({ mode: "enable", name: "nse-mcp", confirmed: true });
  });
  it("keeps the tool name's case", () => expect(mcpArgs(["ALLOW", "x", "getEquity_Details"])).toEqual({ mode: "allow", name: "x", tool: "getEquity_Details" }));
  it("rejects the rest", () => {
    for (const a of [["ENABLE"], ["ENABLE", "a", "NO"], ["ALLOW", "a"], ["DENY", "a", "b", "c"], ["RUN", "a"], ["TEST"]]) expect(mcpArgs(a).mode).toBe("bad");
  });
  it("withTool is sorted and idempotent", () => {
    expect(withTool(["b"], "a", true)).toEqual(["a", "b"]);
    expect(withTool(["a", "b"], "a", true)).toEqual(["a", "b"]);
    expect(withTool(["a", "b"], "a", false)).toEqual(["b"]);
  });
  it("enableStep asks first", () => {
    expect(enableStep(null, "x", false)).toBe("ask");
    expect(enableStep("x", "x", false)).toBe("enable");
    expect(enableStep("y", "x", false)).toBe("ask");
    expect(enableStep(null, "x", true)).toBe("enable");
  });
});
