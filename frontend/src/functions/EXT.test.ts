import { describe, expect, it } from "vitest";
import { gridColumns } from "../research/tablePayload";
import { parseExtArgs, pickRoute, provenance, seriesBars, statusClass, tableSection, type ExtSeries, type ExtTable } from "./extPayload";

describe("EXT command", () => {
  it("bare and LIST show the list", () => {
    expect(parseExtArgs([])).toEqual({ mode: "list" });
    expect(parseExtArgs(["LIST"])).toEqual({ mode: "list" });
    expect(parseExtArgs(["list"])).toEqual({ mode: "list" });
  });

  it("ENABLE and DISABLE need exactly one valid name, lowered", () => {
    expect(parseExtArgs(["ENABLE", "HELLO"])).toEqual({ mode: "enable", name: "hello" });
    expect(parseExtArgs(["disable", "my-ext_2"])).toEqual({ mode: "disable", name: "my-ext_2" });
    expect(parseExtArgs(["ENABLE"]).mode).toBe("usage");
    expect(parseExtArgs(["ENABLE", "a", "b"]).mode).toBe("usage");
    expect(parseExtArgs(["ENABLE", "../x"]).mode).toBe("usage");
  });

  it("a name opens its view with the rest as route and arguments", () => {
    expect(parseExtArgs(["HELLO", "WAVE", "30"])).toEqual({ mode: "view", name: "hello", route: null, rest: ["WAVE", "30"] });
    expect(parseExtArgs(["hello"])).toEqual({ mode: "view", name: "hello", route: null, rest: [] });
    expect(parseExtArgs(["bad/name"]).mode).toBe("usage");
    expect(parseExtArgs(["9lives"]).mode).toBe("usage");
  });

  it("the first word is a route only when the extension has one of that name", () => {
    expect(pickRoute(["WAVE", "30"], ["main", "wave"])).toEqual({ route: "wave", args: ["30"] });
    expect(pickRoute(["Bob"], ["main", "wave"])).toEqual({ route: "main", args: ["Bob"] });
    expect(pickRoute([], ["main"])).toEqual({ route: "main", args: [] });
  });

  it("states map to colours and the provenance line names the author", () => {
    expect(statusClass("ON")).toBe("up");
    expect(statusClass("ERR")).toBe("err");
    expect(statusClass("OFF")).toBe("dim");
    expect(provenance({ name: "hello", version: "0.1.0", author: "Ada", license: "MIT", source: "folder" })).toBe(
      "EXTENSION HELLO 0.1.0 BY ADA (MIT, FOLDER) · THIRD-PARTY CODE",
    );
    expect(provenance({ name: "x", version: null, author: null, license: null, source: "package:p" })).toContain("BY UNKNOWN");
  });
});

describe("EXT payloads", () => {
  const table: ExtTable = {
    kind: "table",
    title: "T",
    columns: [
      { key: "name", title: "Name", kind: "text", align: "left" },
      { key: "chg", title: "Chg", kind: "pct", align: "right" },
    ],
    rows: [
      { name: "<b>x</b>", chg: 0.0452 },
      { name: "y", chg: null },
    ],
  };

  it("a table becomes one section the shared Grid columns can draw, with missing cells as dashes and text left as text", () => {
    const cols = gridColumns(tableSection(table));
    expect(cols.map((c) => c.title)).toEqual(["NAME", "CHG"]);
    expect(cols[0].text(table.rows[0] as never)).toBe("<b>x</b>");
    expect(cols[1].text(table.rows[0] as never)).toBe("+4.52%");
    expect(cols[1].text(table.rows[1] as never)).toBe("—");
    expect(cols[1].align).toBe("right");
  });

  it("a series becomes chart bars; nulls are skipped, never filled in", () => {
    const s: ExtSeries = { kind: "series", title: "S", unit: "pts", t: [86400, 172800, 259200, 345600], v: [1, null, 3, Number.NaN] };
    const { bars, skipped } = seriesBars(s);
    expect(skipped).toBe(2);
    expect(Array.from(bars.t)).toEqual([86400, 259200]);
    expect(Array.from(bars.c)).toEqual([1, 3]);
    expect(Array.from(bars.o)).toEqual([1, 3]);
    expect(bars.interval).toBe("1d");
    expect(bars.symbol).toBe("pts");
  });

  it("a slow series is drawn monthly and an empty one has no bars", () => {
    const monthly: ExtSeries = { kind: "series", title: "M", t: [0, 2_592_000, 5_184_000], v: [1, 2, 3] };
    expect(seriesBars(monthly).bars.interval).toBe("1mo");
    const none = seriesBars({ kind: "series", title: "E", t: [], v: [] });
    expect(none.bars.t.length).toBe(0);
    expect(none.skipped).toBe(0);
  });
});
