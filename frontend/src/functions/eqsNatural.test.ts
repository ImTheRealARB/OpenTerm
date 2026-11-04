import { describe, expect, it } from "vitest";
import { compileFilter, parseFilter, type Universe } from "./eqsFilter";
import { fmtNum, interpretNotes, interpretScreener, looksLikeEnglish } from "./eqsNatural";

const args = (t: string) => interpretScreener(t).args;

describe("interpretScreener: understood phrases", () => {
  const cases: [string, string[]][] = [
    ["tech stocks", ["SECTOR=TECH"]],
    ["technology companies with market cap over 10 billion", ["SECTOR=TECH", "MCAP>10B"]],
    ["healthcare stocks under $50", ["SECTOR=HEALTH", "PRICE<50"]],
    ["banks with price below 30", ["INDUSTRY=BANK", "PRICE<30"]],
    ["financials and energy", ["SECTOR=FINANCE,ENERGY"]],
    ["utilities", ["SECTOR=UTILITIES"]],
    ["consumer staples over $100 billion", ["SECTOR=STAPLES", "MCAP>100B"]],
    ["real estate stocks", ["SECTOR=REAL"]],
    ["large cap tech", ["SECTOR=TECH", "MCAP>10B"]],
    ["mega cap stocks", ["MCAP>200B"]],
    ["mid cap healthcare", ["SECTOR=HEALTH", "MCAP>2B", "MCAP<10B"]],
    ["small-cap biotech", ["INDUSTRY=BIOTECH", "MCAP<2B"]],
    ["stocks over $50 billion", ["MCAP>50B"]],
    ["stocks under $20", ["PRICE<20"]],
    ["price between 10 and 50", ["PRICE>=10", "PRICE<=50"]],
    ["market cap between 2 and 10 billion", ["MCAP>=2B", "MCAP<=10B"]],
    ["volume over 1 million", ["VOL>1M"]],
    ["volume above 500k", ["VOL>500K"]],
    ["trading volume more than 2,000,000", ["VOL>2M"]],
    ["stocks up more than 5%", ["PCT>5"]],
    ["stocks down more than 3%", ["PCT<-3"]],
    ["change greater than 2%", ["PCT>2"]],
    ["gainers", ["PCT>0"]],
    ["losers in energy", ["SECTOR=ENERGY", "PCT<0"]],
    ["chinese tech stocks", ["COUNTRY=CN", "SECTOR=TECH"]],
    ["US software companies", ["INDUSTRY=SOFTWARE", "COUNTRY=US"]],
    ["penny stocks", ["PRICE<5"]],
    ["price at least 5 and at most 20", ["PRICE>=5", "PRICE<=20"]],
    ["price over 10 and under 50", ["PRICE>10", "PRICE<50"]],
    ["tech stocks sorted by volume", ["SECTOR=TECH", "SORT=VOL"]],
    ["energy sort by price ascending", ["SECTOR=ENERGY", "SORT=+PRICE"]],
    ["semiconductors over $100 billion and price under 500", ["INDUSTRY=SEMICONDUCTOR", "MCAP>100B", "PRICE<500"]],
    ["show me healthcare and tech stocks with a market cap of more than 1 billion", ["SECTOR=HEALTH,TECH", "MCAP>1B"]],
  ];
  for (const [text, want] of cases) {
    it(text, () => {
      const r = interpretScreener(text);
      expect(r.unknown, "unknown").toEqual([]);
      expect([...r.args].sort()).toEqual([...want].sort());
    });
  }
});

describe("interpretScreener: honesty", () => {
  it("P/E and dividend yield are not in the data: reported, not guessed", () => {
    const r = interpretScreener("tech stocks with P/E under 20 and dividend yield above 2%");
    expect(r.args).toEqual(["SECTOR=TECH"]);
    expect(r.unavailable).toEqual(["P/E", "DIV YIELD"]);
    expect(r.unknown).toEqual([]);
    expect(interpretNotes(r).join(" ")).toContain("NOT IN SCREENER DATA");
  });
  it("beta is unavailable too", () => {
    expect(interpretScreener("beta below 1").unavailable).toEqual(["BETA"]);
  });
  it("unknown words are listed", () => {
    const r = interpretScreener("tech stocks with sparkly vibes under $50");
    expect(r.unknown).toEqual(["SPARKLY", "VIBES"]);
    expect(r.args).toContain("PRICE<50");
    expect(interpretNotes(r)[0]).toBe("DID NOT UNDERSTAND: SPARKLY VIBES");
  });
  it("a number with no field is not guessed", () => {
    expect(interpretScreener("stocks over 50").unknown.length).toBe(1);
  });
  it("empty text gives nothing", () => {
    expect(interpretScreener("")).toEqual({ args: [], summary: [], unknown: [], unavailable: [] });
  });
  it("summary reads like a filter line", () => {
    const r = interpretScreener("tech stocks under $50 with volume over 1 million");
    expect(r.summary).toEqual(["SECTOR = TECHNOLOGY", "PRICE < $50", "VOLUME > 1M"]);
  });
});

describe("output is valid EQS grammar", () => {
  const u: Universe = {
    rows: [
      ["AAA", "Alpha", 40, 1, 6, 2e6, 3e10, 1, 2000, 1, 1],
      ["BBB", "Beta", 90, 1, 1, 5e5, 5e9, 1, 2000, 1, 1],
      ["CCC", "Gamma", 10, -1, -4, 5e6, 3e11, 1, 2000, 2, 2],
    ],
    sectors: ["", "Technology", "Health Care"],
    industries: ["", "Software", "Biotechnology"],
    countries: ["", "United States"],
  };
  it("parses without errors and filters", () => {
    const r = interpretScreener("tech stocks under $50 with volume over 1 million");
    const f = parseFilter(r.args);
    expect(f.errors).toEqual([]);
    const c = compileFilter(f, u);
    expect(c.errors).toEqual([]);
    expect(u.rows.filter(c.test).map((x) => x[0])).toEqual(["AAA"]);
  });
  it("down more than 3% selects CCC", () => {
    const c = compileFilter(parseFilter(args("down more than 3%")), u);
    expect(u.rows.filter(c.test).map((x) => x[0])).toEqual(["CCC"]);
  });
});

describe("looksLikeEnglish", () => {
  it("English vs EQS syntax", () => {
    expect(looksLikeEnglish("tech stocks with price under 50")).toBe(true);
    expect(looksLikeEnglish("tech stocks")).toBe(true);
    expect(looksLikeEnglish("SECTOR=TECH MCAP>10B")).toBe(false);
    expect(looksLikeEnglish("MCAP > 10B")).toBe(false);
    expect(looksLikeEnglish("TECH")).toBe(false);
    expect(looksLikeEnglish("")).toBe(false);
    expect(looksLikeEnglish("price under 50")).toBe(true);
  });
});

describe("fmtNum", () => {
  it("compacts", () => {
    expect(fmtNum(1e10)).toBe("10B");
    expect(fmtNum(1.5e6)).toBe("1.5M");
    expect(fmtNum(50)).toBe("50");
    expect(fmtNum(-3)).toBe("-3");
    expect(fmtNum(2.5)).toBe("2.5");
  });
});
