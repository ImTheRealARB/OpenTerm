import { describe, expect, it } from "vitest";
import { parseBarsCsv } from "./csvImport";

const csv = (o: string) => `date,open,high,low,close\n2024-01-02,${o},12,9,11\n2024-01-03,10,12,9,11\n`;

describe("csvImport: numbers the backend (Python float) rejects must not preview as valid", () => {
  it.each(["0x10", "0b101", "0o7", "+0x1"])("rejects %s", (raw) => {
    const r = parseBarsCsv(csv(raw));
    expect(r.errors.join(" ")).toContain("BAD NUMBER");
  });
  it("still accepts plain, signed-exponent and decimal numbers", () => {
    expect(parseBarsCsv(csv("1e1")).errors).toEqual([]);
    expect(parseBarsCsv(csv("10.5")).errors).toEqual([]);
  });
});
