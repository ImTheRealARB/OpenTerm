import { describe, expect, it } from "vitest";
import { safeHttpUrl } from "./safeUrl";

describe("safeHttpUrl (audit C-05)", () => {
  it("passes absolute http and https URLs", () => {
    expect(safeHttpUrl("https://www.sec.gov/Archives/x.htm")).toBe("https://www.sec.gov/Archives/x.htm");
    expect(safeHttpUrl("http://127.0.0.1:8888/lab?token=abc")).toBe("http://127.0.0.1:8888/lab?token=abc");
    expect(safeHttpUrl("HTTPS://Example.com/a")).toBe("https://example.com/a"); // returns the parsed (normalised) form
  });

  it("blocks every other scheme", () => {
    for (const u of [
      "javascript:alert(1)",
      "JaVaScRiPt:alert(1)",
      " javascript:alert(1)",
      "java\tscript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "vbscript:x",
      "file:///etc/passwd",
      "blob:https://a.com/uuid",
      "ftp://a.com/x",
      "tg://resolve?domain=x",
    ]) {
      expect(safeHttpUrl(u), u).toBeNull();
    }
  });

  it("blocks relative, empty and non-string input", () => {
    for (const u of ["", "  ", "/api/x", "//evil.com/x", "example.com", null, undefined, 5, {}, ["https://a.com"]]) {
      expect(safeHttpUrl(u as unknown), String(u)).toBeNull();
    }
  });
});
