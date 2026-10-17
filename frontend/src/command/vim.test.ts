import { describe, expect, it } from "vitest";
import { VIM_INSERT, nextWordStart, prevWordStart, vimKey, wordEnd, type VimState } from "./vim";

const N: VimState = { mode: "normal", pending: "" };

/** Feeds keys through the state machine, starting in normal mode unless told otherwise. */
function run(keys: string[], text: string, cursor: number, st: VimState = N) {
  let s = st, t = text, c = cursor;
  const actions: (string | undefined)[] = [];
  for (const k of keys) {
    const r = vimKey(s, k, t, c);
    s = r.state; t = r.text; c = r.cursor;
    actions.push(r.action);
  }
  return { st: s, text: t, cursor: c, actions };
}

describe("word motions", () => {
  const t = "GP AAPL US";
  it("finds word starts and ends", () => {
    expect(nextWordStart(t, 0)).toBe(3);
    expect(nextWordStart(t, 3)).toBe(8);
    expect(prevWordStart(t, 8)).toBe(3);
    expect(prevWordStart(t, 3)).toBe(0);
    expect(wordEnd(t, 0)).toBe(1);
    expect(wordEnd(t, 3)).toBe(6);
  });
});

describe("insert mode", () => {
  it("passes typing through and Escape moves the cursor left into normal mode", () => {
    expect(vimKey(VIM_INSERT, "a", "GP", 2).handled).toBe(false);
    const r = vimKey(VIM_INSERT, "Escape", "GP", 2);
    expect(r).toMatchObject({ handled: true, cursor: 1, state: { mode: "normal" } });
  });

  it("Escape on an empty line stays at 0", () => {
    expect(vimKey(VIM_INSERT, "Escape", "", 0).cursor).toBe(0);
  });
});

describe("normal mode motions", () => {
  it("h l 0 $ ^ w b e move and clamp", () => {
    expect(run(["l", "l"], "GP AAPL", 0).cursor).toBe(2);
    expect(run(["h"], "GP", 0).cursor).toBe(0);
    expect(run(["l", "l", "l", "l"], "GP", 0).cursor).toBe(1);
    expect(run(["$"], "GP AAPL", 0).cursor).toBe(6);
    expect(run(["0"], "GP AAPL", 5).cursor).toBe(0);
    expect(run(["^"], "  GP", 3).cursor).toBe(2);
    expect(run(["w"], "GP AAPL", 0).cursor).toBe(3);
    expect(run(["w", "b"], "GP AAPL", 0).cursor).toBe(0);
    expect(run(["e"], "GP AAPL", 0).cursor).toBe(1);
  });

  it("printable keys never type; unknown named keys fall through", () => {
    const r = vimKey(N, "z", "GP", 0);
    expect(r).toMatchObject({ handled: true, text: "GP" });
    expect(vimKey(N, "F5", "GP", 0).handled).toBe(false);
    for (const k of ["Enter", "Escape", "Tab"]) expect(vimKey(N, k, "GP", 0).handled).toBe(false);
  });
});

describe("entering insert mode", () => {
  it("i a A I place the cursor", () => {
    expect(run(["i"], "GP", 1)).toMatchObject({ st: { mode: "insert" }, cursor: 1 });
    expect(run(["a"], "GP", 0)).toMatchObject({ st: { mode: "insert" }, cursor: 1 });
    expect(run(["A"], "GP AAPL", 0)).toMatchObject({ st: { mode: "insert" }, cursor: 7 });
    expect(run(["I"], "  GP", 4)).toMatchObject({ st: { mode: "insert" }, cursor: 2 });
  });
});

describe("edits", () => {
  it("x deletes under the cursor and D / C cut to the end", () => {
    expect(run(["x"], "GP AAPL", 0)).toMatchObject({ text: "P AAPL", cursor: 0 });
    expect(run(["D"], "GP AAPL", 2)).toMatchObject({ text: "GP", st: { mode: "normal" } });
    expect(run(["C"], "GP AAPL", 2)).toMatchObject({ text: "GP", st: { mode: "insert" } });
  });

  it("dd clears the line, dw cuts a word, d$ and d0 cut to the ends", () => {
    expect(run(["d", "d"], "GP AAPL", 3)).toMatchObject({ text: "", st: { mode: "normal", pending: "" } });
    expect(run(["d", "w"], "GP AAPL US", 3).text).toBe("GP US");
    expect(run(["d", "$"], "GP AAPL", 3).text).toBe("GP ");
    expect(run(["d", "0"], "GP AAPL", 3).text).toBe("AAPL");
    expect(run(["d", "e"], "GP AAPL", 3).text).toBe("GP ");
  });

  it("cw changes the word but keeps the blank; cc replaces the line; both enter insert mode", () => {
    expect(run(["c", "w"], "GP AAPL US", 3)).toMatchObject({ text: "GP  US", st: { mode: "insert" }, cursor: 3 });
    expect(run(["c", "c"], "GP AAPL", 3)).toMatchObject({ text: "", st: { mode: "insert" } });
  });

  it("an unknown motion cancels the pending operator", () => {
    const r = run(["d", "z"], "GP AAPL", 0);
    expect(r.text).toBe("GP AAPL");
    expect(r.st).toEqual(N);
  });
});

describe("history", () => {
  it("k / j (and arrows) ask the caller to walk the history", () => {
    expect(run(["k"], "GP", 0).actions).toEqual(["historyPrev"]);
    expect(run(["j"], "GP", 0).actions).toEqual(["historyNext"]);
    expect(run(["ArrowUp"], "GP", 0).actions).toEqual(["historyPrev"]);
  });
});
