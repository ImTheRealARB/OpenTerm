import { describe, expect, it } from "vitest";
import { eqsBtParams, frmParams, gfParams, GF_METRICS, ibqParams, isEqsBt } from "./fundArgs";

describe("Phase 29 argument parsing", () => {
  it("reads GF, FRM and IBQ words", () => {
    expect(gfParams(["pe", "q", "VS=msft,googl"])).toEqual({ metric: "PE", period: "Q", vs: "MSFT,GOOGL" });
    expect(frmParams(["NetIncomeLoss", "cy2024q4i", "ASOF=2025-01-31"])).toEqual({ tag: "NetIncomeLoss", period: "CY2024Q4I", asof: "2025-01-31" });
    expect(frmParams(["CY2024"])).toBeNull();
    expect(ibqParams(["2023", "industry"])).toEqual({ year: "2023", by: "industry" });
  });

  it("reads EQS BT rules, including >= typed with an equals sign", () => {
    expect(isEqsBt(["bt", "margin>0.1"])).toBe(true);
    expect(eqsBtParams(["margin>0.1", "ROE>=15%", "UNIV=LIST:aapl,msft", "FROM=2021"])).toEqual({
      rules: "MARGIN>0.1 ROE>=15%", univ: "LIST:AAPL,MSFT", start: "2021",
    });
    expect(eqsBtParams(["UNIV=LIST:AAPL"])).toBeNull();
  });

  it("keeps the GF metric list equal to the backend's", () => {
    const fs = (globalThis as unknown as { process: { getBuiltinModule(id: string): { readFileSync(p: string, enc: string): string } } }).process.getBuiltinModule("node:fs");
    const py = fs.readFileSync("../backend/openterm/fund/metrics.py", "utf8");
    const codes = [...py.matchAll(/^ {4}"([A-Z]+)": \(/gm)].map((m) => m[1]).sort();
    expect(codes).toEqual([...GF_METRICS]);
  });
});
