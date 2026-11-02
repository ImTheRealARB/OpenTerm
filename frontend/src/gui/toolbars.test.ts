import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "../functions/registry";
import { TOOLBARS, buttonsFor, expandAsk, keyInit } from "./toolbars";

/** A "single key string" as KeyboardEvent.key reports it: one character, or one of the few named keys panels use. */
const SINGLE_KEY = /^(.|Enter|Escape|Delete|ArrowLeft|ArrowRight|ArrowUp|ArrowDown|PageUp|PageDown|Home|End|F\d{1,2})$/;

describe("GUI panel toolbars", () => {
  it("covers the eight main panels", () => {
    expect(Object.keys(TOOLBARS).sort()).toEqual(["BT", "FA", "GP", "N", "PORT", "Q", "WEI", "WL"]);
  });

  it("only names functions that are in the registry (and built)", () => {
    for (const code of Object.keys(TOOLBARS)) {
      expect(FUNCTIONS.has(code), code).toBe(true);
      expect(FUNCTIONS.get(code)!.load, `${code} is built`).toBeTypeOf("function");
    }
  });

  it("uses a single key string for every button", () => {
    for (const [code, list] of Object.entries(TOOLBARS)) {
      expect(list.length, code).toBeGreaterThan(0);
      for (const b of list) {
        expect(b.key, `${code} ${b.label}`).toMatch(SINGLE_KEY);
        expect(b.label.trim(), code).not.toBe("");
      }
    }
  });

  it("builds a KeyboardEvent init with Shift only where asked", () => {
    const bt = TOOLBARS.BT.find((b) => b.key === "V")!;
    expect(keyInit(bt)).toMatchObject({ key: "V", shiftKey: true });
    expect(keyInit(TOOLBARS.GP[0])).toMatchObject({ key: "1", shiftKey: false });
  });

  it("every ask button names a command that starts with its own function code", () => {
    for (const [code, list] of Object.entries(TOOLBARS)) {
      for (const b of list.filter((x) => x.ask)) {
        expect(b.ask!.command.startsWith(code + " "), `${code} ${b.label}`).toBe(true);
        expect(b.ask!.command).toContain("{input}");
      }
    }
  });

  it("picks the named-list or index buttons of WL by its arguments", () => {
    expect(buttonsFor("WL", ["TECH"]).map((b) => b.label)).toContain("Add");
    expect(buttonsFor("WL", ["TECH"]).map((b) => b.label)).not.toContain("Delete list");
    expect(buttonsFor("WL", []).map((b) => b.label)).toEqual(["Open list", "Delete list"]);
  });

  it("returns nothing for a function without buttons or an empty panel", () => {
    expect(buttonsFor("DES", [])).toEqual([]);
    expect(buttonsFor(undefined, [])).toEqual([]);
  });

  it("expands an ask command", () => {
    expect(expandAsk("WL {arg0} ADD {input}", ["TECH"], "  AAPL MSFT ")).toBe("WL TECH ADD AAPL MSFT");
    expect(expandAsk("PORT {arg0} BASE {input}", [], "INR")).toBe("PORT  BASE INR");
  });
});

describe("firstArg buttons", () => {
  it("BT Templates shows only in the strategy editor", () => {
    const labels = (args: string[]) => buttonsFor("BT", args).map((b) => b.label);
    expect(labels(["EDIT", "mysma"])).toContain("Templates");
    expect(labels(["edit", "mysma"])).toContain("Templates");
    expect(labels(["AAPL", "@mysma"])).not.toContain("Templates");
    expect(labels([])).not.toContain("Templates");
  });
});
