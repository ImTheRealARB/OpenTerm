import { describe, expect, it } from "vitest";
import { chipLine, chipsFor } from "./chips";

describe("question chips (Phase 32)", () => {
  it("board panels name the board tool and fill the country / root", () => {
    const qs = chipsFor("btmm", null, "", ["jp"]);
    expect(qs.length).toBeGreaterThanOrEqual(2);
    expect(qs.every((q) => q.includes("fn btmm") && q.includes("country JP"))).toBe(true);
    expect(chipsFor("ctm", null, "", [])[0]).toContain("root CL");
  });

  it("CN asks for a digest grounded in the news tool, QRY reruns its own query", () => {
    expect(chipsFor("cn", "AAPL", "", [])[0]).toMatch(/news tool for AAPL/);
    expect(chipsFor("qry", null, "", ["last", "FOR", "AAPL"])[0]).toContain('"QRY last FOR AAPL"');
  });

  it("every other table gets 2 generic questions, and the line numbers them", () => {
    const qs = chipsFor("ee", "MSFT", "EE MSFT", []);
    expect(qs).toHaveLength(2);
    expect(chipLine(qs)).toMatch(/^ASK AI \(PRESS 1-2, ESC CANCELS\): 1 .* · {2}2 /);
  });
});

describe("RES (Phase 32)", () => {
  it("asks about the selected paper by its URL, and parses SRC= DAYS= words", async () => {
    const { resParams } = await import("./resArgs");
    const qs = chipsFor("res", null, "RES", [], { title: "Tail events", url: "https://www.bis.org/publications/wp1398" });
    expect(qs[0]).toContain("read_url on https://www.bis.org/publications/wp1398");
    expect(resParams(["src=bis", "DAYS=30", "monetary", "policy"])).toEqual({ src: "BIS", days: "30", q: "monetary policy" });
    expect(resParams([])).toEqual({});
  });
});
