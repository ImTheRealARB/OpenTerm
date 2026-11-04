import { describe, expect, it } from "vitest";
import { handleLibrary, isLibraryMsg, MAX_ITEMS } from "./libraryWorker";
import { synth } from "./library/synth";

describe("library worker handler", () => {
  const series = synth(120);
  it("answers catalog and formula items, errors per item", () => {
    const { msg, transfer } = handleLibrary({
      type: "library",
      id: 7,
      series,
      items: [{ key: "a", id: "MACD", params: [12, 26, 9] }, { key: "b", formula: "EMA(close,12)-EMA(close,26)" }, { key: "c", formula: "EMA(close," }, { key: "d", id: "NOPE" }],
    });
    expect(msg.id).toBe(7);
    const a = msg.results.a;
    expect(a.ok && a.data.length === 3 && a.outputs[0] === "macd").toBe(true);
    expect(msg.results.b.ok).toBe(true);
    expect(msg.results.c).toMatchObject({ ok: false, pos: 10 });
    expect(msg.results.d).toMatchObject({ ok: false, error: "UNKNOWN INDICATOR NOPE" });
    expect(transfer.length).toBe(4);
  });
  it("caps the item count and recognises its messages", () => {
    const items = Array.from({ length: 30 }, (_, i) => ({ key: `k${i}`, id: "SMA" }));
    expect(Object.keys(handleLibrary({ type: "library", id: 1, series, items }).msg.results).length).toBe(MAX_ITEMS);
    expect(isLibraryMsg({ type: "library" })).toBe(true);
    expect(isLibraryMsg({ id: 1, series: {}, which: [] })).toBe(false);
    expect(isLibraryMsg(null)).toBe(false);
  });
});
