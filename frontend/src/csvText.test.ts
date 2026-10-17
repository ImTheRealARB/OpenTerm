import { describe, expect, it } from "vitest";
import { csvField, csvFileName, neutralize, toCsv } from "./csvText";

describe("csv", () => {
  it("quotes only when needed and doubles quotes", () => {
    expect(csvField("AAPL")).toBe("AAPL");
    expect(csvField("Apple, Inc.")).toBe('"Apple, Inc."');
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
    expect(csvField("two\nlines")).toBe('"two\nlines"');
    expect(csvField("cr\rhere")).toBe('"cr\rhere"');
    expect(csvField(" padded ")).toBe('" padded "');
  });

  it("writes numbers, blanks and booleans plainly", () => {
    expect(csvField(1.5)).toBe("1.5");
    expect(csvField(-0.25)).toBe("-0.25");
    expect(csvField(NaN)).toBe("");
    expect(csvField(null)).toBe("");
    expect(csvField(undefined)).toBe("");
    expect(csvField(true)).toBe("true");
  });

  it("neutralizes spreadsheet formulas but keeps signed figures", () => {
    expect(neutralize("=HYPERLINK(1)")).toBe("'=HYPERLINK(1)");
    expect(neutralize("@SUM(A1)")).toBe("'@SUM(A1)");
    expect(neutralize("+cmd")).toBe("'+cmd");
    expect(neutralize("-cmd")).toBe("'-cmd");
    expect(neutralize("+1.25%")).toBe("+1.25%");
    expect(neutralize("-3.40")).toBe("-3.40");
    expect(neutralize("-.5")).toBe("-.5");
    expect(csvField("=1+1,2")).toBe(`"'=1+1,2"`);
  });

  it("serializes a table with CRLF records", () => {
    expect(toCsv(["SYM", "NAME", "LAST"], [["AAPL", "Apple, Inc.", 342], ["X", null, -1.5]])).toBe(
      'SYM,NAME,LAST\r\nAAPL,"Apple, Inc.",342\r\nX,,-1.5\r\n',
    );
    expect(toCsv(["A"], [])).toBe("A\r\n");
  });

  it("makes safe file names", () => {
    expect(csvFileName("EQS SECTOR=TECH MCAP>10B")).toBe("EQS_SECTOR_TECH_MCAP_10B.csv");
    expect(csvFileName("Q_^GSPC_EURUSD=X")).toBe("Q_GSPC_EURUSD_X.csv");
    expect(csvFileName("///")).toBe("export.csv");
    expect(csvFileName("x".repeat(200))).toHaveLength(84);
  });
});
