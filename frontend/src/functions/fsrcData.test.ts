import { describe, expect, it } from "vitest";
import type { FsrcPayload, FsrcRow } from "../net/etfTypes";
import { FSRC_EMPTY, mergeFsrc } from "./fsrcData";

const payload = (over: Partial<FsrcPayload>): FsrcPayload => ({
  run: "r1", reset: false, seq: 0, rows: [], universe: 3, loaded: 0, nodata: 0, failed: 0, state: "loading", partial: true,
  note: null, universe_source: "x", file_stamp: null, ...over,
});
const row = (s: string, fee: number): FsrcRow => [s, `${s} ETF`, fee, 1e9, "Large Blend", "Fam"];

describe("FSRC merge", () => {
  it("adds installments, replaces a fund fetched again, and starts over on reset", () => {
    let held = mergeFsrc(FSRC_EMPTY, payload({ reset: true, seq: 2, rows: [row("AAA", 0.1), row("BBB", 0.2)] }));
    held = mergeFsrc(held, payload({ seq: 4, rows: [row("CCC", 0.3), row("AAA", 0.05)] }));
    expect([...held.rows.keys()]).toEqual(["AAA", "BBB", "CCC"]);
    expect(held.rows.get("AAA")?.[2]).toBe(0.05);
    expect(held.seq).toBe(4);
    held = mergeFsrc(held, payload({ run: "r2", reset: true, seq: 1, rows: [row("ZZZ", 0.4)] })); // server restarted
    expect([...held.rows.keys()]).toEqual(["ZZZ"]);
    expect(held.run).toBe("r2");
  });
});
