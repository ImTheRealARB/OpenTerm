import { describe, expect, it } from "vitest";
import { gridCsv } from "./tableExport";
import type { Column } from "../components/Grid";

interface Row {
  sym: string;
  px: number;
}

const cols = [
  { title: "", width: 1, aux: true, text: () => "" },
  { title: "SYM", width: 8, text: (r: Row) => r.sym },
  { title: "2DAY", width: 9, aux: true, text: () => "" },
  { title: "PX", width: 8, text: (r: Row) => String(r.px) },
] as Column<Row>[];

describe("gridCsv", () => {
  it("leaves aux columns out of the header and the rows (audit M-14)", () => {
    const t = gridCsv("T", cols, [{ sym: "AAPL", px: 1 }]);
    expect(t.header).toEqual(["SYM", "PX"]);
    expect(t.rows).toEqual([["AAPL", "1"]]);
  });
});
