import { describe, expect, it } from "vitest";
import {
  faArgs,
  faRows,
  filingForm,
  fmtFrac,
  fmtShares,
  fmtStatement,
  holderRows,
  insiderTotals,
  unitNote,
  type FaPayload,
  type FaPeriodInfo,
  type HoldersPayload,
  type InsiderTrade,
} from "./secTables";

const period = (label: string, derived = false): FaPeriodInfo => ({ key: label, label, end: "2025-09-27", start: null, fy: 2025, fp: "FY", form: "10-K", filed: "2025-10-31", derived });
const payload: FaPayload = {
  symbol: "TEST", cik: 1, name: "Test Inc", currency: "USD", period: "Q", source: "sec",
  periods: [period("Q4 FY25", true), period("Q3 FY25"), period("Q2 FY25")],
  statements: {
    IS: [
      { key: "revenue", label: "Revenue", unit: "USD", values: [94_930_000_000, 85_777_000_000, null], flags: ["d", "", ""], tags: ["Revenues", "Revenues", null] },
      { key: "eps", label: "EPS diluted", unit: "USD/shares", values: [1.64, 1.4, 1.65], flags: ["", "", ""], tags: [null, null, null] },
    ],
    BS: [],
    CF: [{ key: "fcf", label: "Free cash flow", unit: "USD", values: [-5_000_000, 1_000_000, 2_500_000], flags: ["c", "c", "c"], tags: [null, null, null], computed: true }],
  },
};

describe("faArgs", () => {
  it("accepts period and statement in any order, any case", () => {
    expect(faArgs([])).toEqual({ period: "A", tab: "IS" });
    expect(faArgs(["q", "cf"])).toEqual({ period: "Q", tab: "CF" });
    expect(faArgs(["BS", "A"])).toEqual({ period: "A", tab: "BS" });
    expect(faArgs(["nonsense"])).toEqual({ period: "A", tab: "IS" });
  });
});

describe("fmtStatement", () => {
  it("shows USD in millions, per-share with 2 decimals, dash for missing", () => {
    expect(fmtStatement(94_930_000_000, "USD")).toBe("94,930");
    expect(fmtStatement(-5_000_000, "USD")).toBe("-5.0");
    expect(fmtStatement(1.639, "USD/shares")).toBe("1.64");
    expect(fmtStatement(14_800_000_000, "shares")).toBe("14,800");
    expect(fmtStatement(null, "USD")).toBe("—");
    expect(fmtStatement(NaN, "USD")).toBe("—");
  });
  it("names the unit for the footer", () => {
    expect(unitNote("USD")).toBe("USD MILLIONS");
    expect(unitNote("USD/shares")).toBe("USD PER SHARE");
    expect(unitNote("shares")).toBe("MILLIONS OF SHARES");
  });
});

describe("faRows", () => {
  it("marks derived cells with a star and keeps missing cells as dashes", () => {
    const { periods, rows } = faRows(payload, "IS");
    expect(periods.map((p) => p.label)).toEqual(["Q4 FY25", "Q3 FY25", "Q2 FY25"]);
    expect(rows[0].cells).toEqual(["94,930*", "85,777", "—"]);
    expect(rows[1].cells).toEqual(["1.64", "1.40", "1.65"]);
  });
  it("scrolls to older periods and caps the column count", () => {
    const older = faRows(payload, "IS", 1);
    expect(older.periods.map((p) => p.label)).toEqual(["Q3 FY25", "Q2 FY25"]);
    expect(older.rows[0].cells).toEqual(["85,777", "—"]);
    expect(faRows(payload, "IS", 0, 2).periods).toHaveLength(2);
    expect(faRows(payload, "IS", 99).periods).toHaveLength(1); // never scrolls past the oldest period
  });
  it("flags computed rows and tolerates an empty statement", () => {
    expect(faRows(payload, "CF").rows[0]).toMatchObject({ computed: true, cells: ["-5.0", "1.0", "2.5"] });
    expect(faRows(payload, "BS").rows).toEqual([]);
  });
});

describe("filingForm", () => {
  it("uppercases the first argument", () => {
    expect(filingForm(["10-k"])).toBe("10-K");
    expect(filingForm([])).toBe("");
  });
});

describe("number helpers", () => {
  it("formats shares and fractions", () => {
    expect(fmtShares(1234567.4)).toBe("1,234,567");
    expect(fmtShares(null)).toBe("—");
    expect(fmtFrac(0.0797)).toBe("7.97%");
    expect(fmtFrac(null)).toBe("—");
  });
});

describe("holderRows", () => {
  const p: HoldersPayload = {
    symbol: "TEST",
    breakdown: { insiders_pct: 0.0165, institutions_pct: 0.65, institutions_float_pct: 0.66, institutions_count: 7000 },
    institutions: [{ holder: "Vanguard", pct_held: 0.0966, shares: 1_400_000_000, value: 3.5e11, pct_change: -0.01, report_date: "2026-06-30" }],
    funds: [],
    source: "yahoo_own",
  };
  it("lays out summary, institutions and skips an empty fund list", () => {
    const rows = holderRows(p);
    expect(rows.filter((r) => r.section).map((r) => r.section)).toEqual(["MAJOR HOLDERS", "TOP INSTITUTIONS"]);
    expect(rows[1]).toMatchObject({ holder: "Insiders", pct: "1.65%" });
    expect(rows[4]).toMatchObject({ holder: "Number of institutions", pct: "7000" });
    expect(rows[rows.length - 1]).toMatchObject({ holder: "Vanguard", pct: "9.66%", date: "2026-06-30" });
  });
});

describe("insiderTotals", () => {
  const t = (code: string, value: number | null): InsiderTrade => ({
    owner: "X", owner_cik: null, relation: "", date: null, code, code_text: "", acq_disp: null, shares: null, price: null, value,
    owned_after: null, direct: null, security: null, derivative: false, accession: null, filed: null, url: null,
  });
  it("sums only open-market purchases and sales", () => {
    expect(insiderTotals([t("S", 100), t("S", 50), t("P", 20), t("M", 999), t("A", 5), t("S", null)])).toEqual({ bought: 20, sold: 150 });
  });
});
