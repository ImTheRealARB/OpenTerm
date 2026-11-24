import { describe, expect, it } from "vitest";
import type { FsrcRow } from "../net/etfTypes";
import { parseFsrcFilter, screenFsrc } from "./fsrcFilter";

const ROWS: FsrcRow[] = [
  ["VOO", "Vanguard S&P 500 ETF", 0.03, 1.7e12, "Large Blend", "Vanguard"],
  ["QQQ", "Invesco QQQ Trust", 0.18, 4.6e11, "Large Growth", "Invesco"],
  ["ARKK", "ARK Innovation ETF", 0.75, 6e9, "Mid-Cap Growth", "ARK"],
  ["XLK", "Technology Select Sector SPDR", 0.08, 1.2e11, "Technology", "State Street"],
  ["NOFEE", "Fund with no fee data", null, 5e8, "Large Blend", null],
];
const run = (args: string[], complete = true) => screenFsrc(ROWS, parseFsrcFilter(args), complete);

describe("FSRC filter grammar", () => {
  it("ANDs fee, size and category terms and reads suffixes and spaces around the operator", () => {
    // FEE is percent; an unknown fee never passes a fee test (NOFEE is Large Blend but has no fee)
    expect(run(["FEE<0.2", "AUM>1B", "CAT=LARGE"]).rows.map((r) => r[0])).toEqual(["VOO", "QQQ"]);
    expect(run(["FEE", "<", "0.1", "CAT!=TECH"]).rows.map((r) => r[0])).toEqual(["VOO"]);
    expect(run(["CAT=LARGE_BLEND"]).rows.map((r) => r[0])).toEqual(["VOO", "NOFEE"]); // _ is a space; default sort is size, largest first
    expect(run(["cat=growth"]).rows.map((r) => r[0])).toEqual(["QQQ", "ARKK"]); // a prefix of a word, any case
  });

  it("sorts: fee cheapest first, size largest first, a forced direction wins, unknowns last", () => {
    expect(run(["SORT=FEE"]).rows.map((r) => r[0])).toEqual(["VOO", "XLK", "QQQ", "ARKK", "NOFEE"]);
    expect(run(["SORT=-FEE"]).rows.map((r) => r[0])).toEqual(["ARKK", "QQQ", "XLK", "VOO", "NOFEE"]);
    expect(run(["SORT=SYMBOL"]).rows.map((r) => r[0])).toEqual(["ARKK", "NOFEE", "QQQ", "VOO", "XLK"]);
  });

  it("names what it cannot read; a category that matches nothing is an error only once loading is complete", () => {
    expect(parseFsrcFilter(["FEE<abc", "COLOUR=RED", "AAPL", "SORT=PRICE"]).errors).toEqual([
      "FEE: ABC IS NOT A NUMBER", "UNKNOWN FIELD COLOUR", "CANNOT READ AAPL", "CANNOT SORT BY PRICE",
    ]);
    expect(run(["CAT=CRYPTO"], true).errors).toEqual(["NO CATEGORY MATCHES CRYPTO"]);
    expect(run(["CAT=CRYPTO"], false).errors).toEqual([]); // partial: that category may not have loaded yet
  });
});
