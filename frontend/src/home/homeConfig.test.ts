import { describe, expect, it } from "vitest";
import { TAPE_DEFAULT, TAPE_SYMBOL_RE } from "../settings/schema";
import { newsQuery as newsArgs } from "../functions/newsArgs";
import { BLOCKS, BLOCK_DRILL, NEWS_SECTIONS, blockSymbols, homeSymbols, mergeNews, newsQuery, tapeLabel } from "./homeConfig";

describe("home blocks", () => {
  it("every symbol is a valid tape-style symbol and appears once", () => {
    const syms = blockSymbols();
    expect(syms.length).toBeGreaterThan(20);
    expect(new Set(syms).size).toBe(syms.length);
    for (const s of syms) expect(TAPE_SYMBOL_RE.test(s), s).toBe(true);
    for (const s of TAPE_DEFAULT) expect(TAPE_SYMBOL_RE.test(s), s).toBe(true);
  });

  it("block ids are unique and news sections are ones the server knows", () => {
    const ids = BLOCKS.map((b) => b.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const b of BLOCKS) if (b.kind === "news") for (const s of b.sections) if (s) expect(NEWS_SECTIONS).toContain(s);
  });

  it("homeSymbols joins the tape and the blocks without repeats", () => {
    const all = homeSymbols(["^GSPC", "AAPL"]);
    expect(all.filter((s) => s === "^GSPC").length).toBe(1);
    expect(all).toContain("AAPL");
    expect(all).toContain("^NSEI");
  });
});

describe("block drill links", () => {
  it("name real blocks, run their own code, and every news run is a command the N function accepts", () => {
    const ids = BLOCKS.map((b) => b.id);
    for (const [id, d] of Object.entries(BLOCK_DRILL)) {
      expect(ids, id).toContain(id);
      expect(d.run.split(" ")[0]).toBe(d.code);
      if (d.code === "N") expect(newsArgs(d.run.split(" ").slice(1)).kind, d.run).not.toBe("error");
    }
  });
});

describe("tapeLabel", () => {
  it("shortens known names and cleans up the rest", () => {
    expect(tapeLabel("^GSPC")).toBe("SPX");
    expect(tapeLabel("GC=F")).toBe("GOLD");
    expect(tapeLabel("USDINR=X")).toBe("USD/INR");
    expect(tapeLabel("EURUSD=X")).toBe("EUR/USD");
    expect(tapeLabel("BTC-USD")).toBe("BTC");
    expect(tapeLabel("RELIANCE.NS")).toBe("RELIANCE");
    expect(tapeLabel("^FOO")).toBe("FOO");
    expect(tapeLabel("AAPL")).toBe("AAPL");
  });
});

describe("mergeNews / newsQuery", () => {
  const item = (id: string, published: number | null) => ({ id, published });
  it("merges newest first, drops repeats and caps the length", () => {
    const out = mergeNews([[item("a", 10), item("b", 30)], [item("b", 30), item("c", 20), item("d", null)]], 3);
    expect(out.map((x) => x.id)).toEqual(["b", "c", "a"]);
  });
  it("the query carries the section only when there is one", () => {
    expect(newsQuery("markets", 6)).toEqual({ section: "markets", limit: "6" });
    expect(newsQuery(undefined, 8)).toEqual({ limit: "8" });
  });
});
