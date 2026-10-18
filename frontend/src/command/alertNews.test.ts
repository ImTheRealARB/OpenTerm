import { describe, expect, it } from "vitest";
import { newsMatch, parseAlrt } from "./alertArgs";

describe("ALRT NEWS", () => {
  it("takes a word and an optional symbol", () => {
    expect(parseAlrt(["NEWS", "recall", "aapl"])).toEqual({ kind: "createNews", word: "RECALL", symbol: "AAPL" });
    expect(parseAlrt(["NEWS", "split"])).toEqual({ kind: "createNews", word: "SPLIT", symbol: null });
  });

  it("uses the typed security when no symbol follows", () => {
    expect(parseAlrt(["NEWS", "probe"], { symbol: "MSFT" })).toEqual({ kind: "createNews", word: "PROBE", symbol: "MSFT" });
    expect(parseAlrt(["NEWS", "probe", "TSLA"], { symbol: "MSFT" })).toMatchObject({ symbol: "TSLA" });
  });

  it("accepts a quoted phrase", () => {
    expect(parseAlrt(["NEWS", '"stock', 'split"', "AAPL"])).toEqual({ kind: "createNews", word: "STOCK SPLIT", symbol: "AAPL" });
    expect(parseAlrt(["NEWS", '"stock', 'split"'])).toEqual({ kind: "createNews", word: "STOCK SPLIT", symbol: null });
  });

  it("refuses a missing, short or odd word and extra words", () => {
    for (const args of [["NEWS"], ["NEWS", "a"], ["NEWS", "bad;word"], ["NEWS", "two", "words", "here"]]) {
      expect(parseAlrt(args)).toMatchObject({ kind: "error" });
    }
    expect(parseAlrt(["NEWS", "recall", "A B"])).toMatchObject({ kind: "error" });
  });

  it("deletes and rearms news alerts by N<id>", () => {
    expect(parseAlrt(["DEL", "N3"])).toEqual({ kind: "delete", id: 3, news: true });
    expect(parseAlrt(["REARM", "n12"])).toEqual({ kind: "rearm", id: 12, news: true });
    expect(parseAlrt(["DEL", "3"])).toEqual({ kind: "delete", id: 3 });
    expect(parseAlrt(["DEL", "N0"])).toMatchObject({ kind: "error" });
    expect(parseAlrt(["DEL", "NX"])).toMatchObject({ kind: "error" });
  });

  it("leaves price alerts alone", () => {
    expect(parseAlrt(["AAPL", ">", "200"])).toMatchObject({ kind: "create", symbol: "AAPL" });
  });
});

describe("newsMatch", () => {
  it("matches whole words, any case, with an optional plural s", () => {
    expect(newsMatch("RECALL", "Apple announces recall of chargers")).toBe(true);
    expect(newsMatch("recall", "Recalls widen")).toBe(true);
    expect(newsMatch("RECALL", "Precall notice")).toBe(false);
    expect(newsMatch("SPLIT", "Splitting the bill")).toBe(false);
    expect(newsMatch("STOCK SPLIT", "Tesla announces 3-for-1 stock split")).toBe(true);
  });

  it("treats punctuation in the word literally", () => {
    expect(newsMatch("U.S.", "U.S. stocks rise")).toBe(true);
    expect(newsMatch("U.S.", "UXSX stocks rise")).toBe(false);
    expect(newsMatch("S&P", "S&P 500 hits record")).toBe(true);
  });

  it("never matches an empty word", () => {
    expect(newsMatch("", "anything")).toBe(false);
    expect(newsMatch("  ", "anything")).toBe(false);
  });
});
