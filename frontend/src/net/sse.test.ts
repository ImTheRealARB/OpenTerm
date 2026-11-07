import { describe, expect, it } from "vitest";
import { parseSse } from "./sse";

const ev = (e: unknown) => `data: ${JSON.stringify(e)}\n\n`;

describe("parseSse", () => {
  it("returns whole events and keeps a partial one for the next chunk", () => {
    const a = ev({ type: "token", text: "he" });
    const b = ev({ type: "token", text: "llo" });
    const first = parseSse(a + b.slice(0, 10));
    expect(first.events).toEqual([{ type: "token", text: "he" }]);
    const second = parseSse(first.rest + b.slice(10));
    expect(second.events).toEqual([{ type: "token", text: "llo" }]);
    expect(second.rest).toBe("");
  });

  it("skips comments and lines that are not valid JSON", () => {
    expect(parseSse(": ping\n\ndata: {oops\n\n" + ev({ type: "notice", text: "x" })).events).toEqual([{ type: "notice", text: "x" }]);
  });

  it("accepts CRLF separators", () => {
    expect(parseSse('data: {"type":"token","text":"a"}\r\n\r\n').events).toHaveLength(1);
  });
});
