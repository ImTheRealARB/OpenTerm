import { describe, expect, it } from "vitest";
import { GLOSSARY, explain } from "./glossary";

// vitest runs in Node without @types/node, so reach the file system through Node's own built-in loader (as themes.test.ts does).
interface Fs {
  readFileSync(p: URL, enc: string): string;
  readdirSync(p: URL): string[];
}
const fs = (globalThis as unknown as { process: { getBuiltinModule(id: string): Fs } }).process.getBuiltinModule("node:fs");

/** Every glossary term a source file uses: data-term="X", termProps("X", ...) and the TERM_OF map in DES.tsx. */
function termsUsed(): { file: string; term: string }[] {
  const out: { file: string; term: string }[] = [];
  for (const dir of ["../functions/", "./", "../components/"]) {
    for (const f of fs.readdirSync(new URL(dir, import.meta.url))) {
      if (!f.endsWith(".tsx")) continue;
      const src = fs.readFileSync(new URL(dir + f, import.meta.url), "utf8");
      for (const m of src.matchAll(/data-term="([^"]+)"|termProps\("([^"]+)"/g)) out.push({ file: f, term: m[1] ?? m[2] });
      const map = /const TERM_OF[^{]*\{([^}]*)\}/.exec(src);
      if (map) for (const m of map[1].matchAll(/:\s*"([^"]+)"/g)) out.push({ file: f, term: m[1] });
    }
  }
  return out;
}

describe("glossary", () => {
  it("has the beginner terms the spec lists", () => {
    for (const t of ["P/E", "EPS", "MARKET CAP", "OHLC", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "DIVIDEND YIELD", "BETA", "52-WEEK RANGE",
      "DRAWDOWN", "SHARPE", "SORTINO", "CAGR", "VOLATILITY", "BID", "ASK", "SPREAD", "FLOAT", "SHARES OUTSTANDING", "P/B", "P/S", "EV/EBITDA", "ROE", "MARGIN", "YIELD", "DURATION"]) {
      expect(explain(t), t).toBeTruthy();
    }
  });

  it("every entry is one plain sentence-ish line, and keys are upper case", () => {
    for (const [k, v] of Object.entries(GLOSSARY)) {
      expect(k, k).toBe(k.toUpperCase());
      expect(v.length, k).toBeGreaterThan(20);
      expect(v.length, k).toBeLessThan(260);
    }
  });

  it("every term used by a data-term attribute in the source has an entry", () => {
    const used = termsUsed();
    expect(used.length).toBeGreaterThan(5); // the scan itself works
    for (const { file, term } of used) expect(explain(term), `${term} (in ${file})`).toBeTruthy();
  });

  it("explains EPS in plain words", () => {
    expect(explain("eps")).toMatch(/earnings/i);
    expect(explain("EPS")).toMatch(/per share/i);
  });
});
