import { describe, expect, it } from "vitest";
import { parseSandboxError } from "./sandboxError";

describe("parseSandboxError", () => {
  it("splits the LINE prefix from the message", () => {
    expect(parseSandboxError("LINE 3: IMPORT os IS NOT ALLOWED (allowed: numpy)")).toEqual({
      line: 3,
      message: "IMPORT os IS NOT ALLOWED (allowed: numpy)",
    });
  });
  it("returns null line for errors about the whole strategy", () => {
    expect(parseSandboxError("EMPTY STRATEGY")).toEqual({ line: null, message: "EMPTY STRATEGY" });
  });
  it("accepts lowercase and extra spaces", () => {
    expect(parseSandboxError("  line  12 :  bad thing ")).toEqual({ line: 12, message: "bad thing" });
  });
  it("only strips a prefix at the start", () => {
    expect(parseSandboxError("SYNTAX ERROR NEAR LINE 3: x")).toEqual({ line: null, message: "SYNTAX ERROR NEAR LINE 3: x" });
  });
  it("treats LINE 0 as no line", () => {
    expect(parseSandboxError("LINE 0: odd").line).toBeNull();
  });
  it("keeps multi-line messages whole", () => {
    expect(parseSandboxError("LINE 2: a\nb")).toEqual({ line: 2, message: "a\nb" });
  });
});
