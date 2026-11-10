import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "../functions/registry";
import { TOOLBARS, askButton, askCommands, buttonsFor, expandAsk, keyHint, keyInit } from "./toolbars";

/** A "single key string" as KeyboardEvent.key reports it: one character, or one of the few named keys panels use. */
const SINGLE_KEY = /^(.|Enter|Escape|Delete|ArrowLeft|ArrowRight|ArrowUp|ArrowDown|PageUp|PageDown|Home|End|F\d{1,2})$/;

describe("GUI panel toolbars", () => {
  it("covers the main panels", () => {
    expect(Object.keys(TOOLBARS).sort()).toEqual(["ALRT", "BT", "DES", "FA", "GP", "JRNL", "N", "PORT", "Q", "SYNC", "WEI", "WL"]);
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
        // DES "Set alert" runs an ALRT command for the panel's stock, so it starts with ALRT.
        expect(b.ask!.command.startsWith(code + " ") || b.ask!.command.startsWith("ALRT "), `${code} ${b.label}`).toBe(true);
        expect(b.ask!.command).toContain("{input}");
      }
    }
  });

  it("fills {symbol} and splits comma-separated entries", () => {
    expect(expandAsk("ALRT {symbol} > {input}", [], "200", "AAPL")).toBe("ALRT AAPL > 200");
    const port = TOOLBARS.PORT.find((b) => b.label === "Add")!.ask!;
    expect(askCommands(port, ["MAIN"], "AAPL 10 150, MSFT 5 300")).toEqual(["PORT MAIN ADD AAPL 10 150", "PORT MAIN ADD MSFT 5 300"]);
    expect(askButton("ALRT", "Add an alert")?.ask?.command).toBe("ALRT {input}");
  });

  it("picks the named-list or index buttons of WL by its arguments", () => {
    expect(buttonsFor("WL", ["TECH"]).map((b) => b.label)).toContain("Add");
    expect(buttonsFor("WL", ["TECH"]).map((b) => b.label)).not.toContain("Delete list");
    expect(buttonsFor("WL", []).map((b) => b.label)).toEqual(["Open list", "Delete list"]);
  });

  it("returns nothing for a function without buttons or an empty panel", () => {
    expect(buttonsFor("MOST", [])).toEqual([]);
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

describe("keyHint (the letter before a label in the function band)", () => {
  it("shows plain letters only", () => {
    const find = (code: string, label: string) => TOOLBARS[code].find((b) => b.label === label)!;
    expect(keyHint(find("Q", "Add"))).toBe("A");
    expect(keyHint(find("Q", "Sort"))).toBe("S");
    expect(keyHint(find("GP", "Log"))).toBe("L");
    expect(keyHint(find("GP", "1Y"))).toBe(""); // a digit: the label is the meaning
    expect(keyHint(find("GP", "Price alert"))).toBe(""); // Shift chord
    expect(keyHint(find("GP", "Indicators…"))).toBe(""); // opens another panel
    expect(keyHint(find("Q", "Details"))).toBe(""); // Enter
  });
});
