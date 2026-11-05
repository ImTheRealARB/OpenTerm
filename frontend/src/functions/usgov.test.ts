import { describe, expect, it } from "vitest";
import { CATEGORY_OF } from "./categories";
import { FUNCTIONS } from "./registry";
import { agencyShort, billCommandArgs, billLabel, coverage, FEDREG_TYPES, fecWhere, fmtUsd, joinQuery } from "./usgovArgs";

// No @types/node here, so Node modules come from process.getBuiltinModule (see CLAUDE.md "vitest blanks CSS imports").
const nodeFs = (globalThis as unknown as { process: { getBuiltinModule(id: string): { readFileSync(p: string, enc: string): string } } }).process.getBuiltinModule("node:fs");

describe("USASP FEDREG FEC CONGRESS registry entries", () => {
  it.each(["USASP", "FEDREG", "FEC", "CONGRESS"])("%s is registered with a loader, no security and a category", (code) => {
    const def = FUNCTIONS.get(code);
    expect(def?.load).toBeTypeOf("function");
    expect(def?.needsSecurity).toBe(false);
    expect(CATEGORY_OF[code]).toBe("Research");
  });
});

describe("usgov helpers", () => {
  it("joins every word after the code into one query", () => {
    expect(joinQuery(["lockheed", "martin"])).toBe("lockheed martin");
    expect(joinQuery(["", " "])).toBe("");
    expect(joinQuery(["AGENCY:Department of Defense"])).toBe("AGENCY:Department of Defense");
  });

  it("formats dollars short, keeps the sign, and never turns a missing amount into $0", () => {
    expect(fmtUsd(34100007952.06)).toBe("$34.10B");
    expect(fmtUsd(2.02e12)).toBe("$2.02T");
    expect(fmtUsd(4_500_000)).toBe("$4.50M");
    expect(fmtUsd(12_345)).toBe("$12.3K");
    expect(fmtUsd(950)).toBe("$950");
    expect(fmtUsd(0)).toBe("$0");
    expect(fmtUsd(-2_000_000)).toBe("-$2.00M");
    expect(fmtUsd(null)).toBe("");
    expect(fmtUsd(undefined)).toBe("");
    expect(fmtUsd(Number.NaN)).toBe("");
  });

  it("shortens an agency list to the first plus a count", () => {
    expect(agencyShort([])).toBe("");
    expect(agencyShort(["EPA"])).toBe("EPA");
    expect(agencyShort(["Commerce Department", "Foreign-Trade Zones Board"])).toBe("Commerce Department +1");
  });

  it("labels bills and builds the command that opens one", () => {
    expect(billLabel({ type: "HR", number: "9001" })).toBe("HR 9001");
    expect(billCommandArgs({ congress: 119, type: "S", number: "4242" })).toEqual(["119", "S", "4242"]);
  });

  it("describes a FEC row's office and place, and a missing coverage date", () => {
    expect(fecWhere({ office: "House", state: "CA", district: "12" })).toBe("House CA-12");
    expect(fecWhere({ office: "Senate", state: "TX", district: null })).toBe("Senate TX");
    expect(fecWhere({ office: null, state: null, district: null })).toBe("");
    expect(coverage("2026-09-30")).toBe("2026-09-30");
    expect(coverage(null)).toBe("NOT GIVEN");
  });

  it("FEDREG type words match the backend's list", () => {
    const py = nodeFs.readFileSync("../backend/openterm/world/fedreg.py", "utf-8");
    const m = /TYPES = \{([^}]*)\}/.exec(py);
    const backend = [...(m?.[1] ?? "").matchAll(/"([A-Z]+)":/g)].map((x) => x[1]);
    expect(backend).toEqual([...FEDREG_TYPES]);
  });
});
