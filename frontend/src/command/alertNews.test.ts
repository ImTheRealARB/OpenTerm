import { describe, expect, it } from "vitest";
import { newsMatch, parseAlrt, viaText } from "./alertArgs";

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

describe("ALRT ... VIA (per-alert delivery channels)", () => {
  it("reads VIA after a price rule and maps TG to telegram", () => {
    expect(parseAlrt(["AAPL", ">", "200", "VIA", "TG,EMAIL"])).toEqual({
      kind: "create", symbol: "AAPL", rule: { op: ">", unit: "price", value: 200 }, channels: ["telegram", "email"],
    });
    // lower case, spaces around commas and the full word all work; a repeated channel counts once
    expect(parseAlrt(["aapl", "+5%", "via", "tg,", "Telegram", "webhook"])).toMatchObject({ kind: "create", channels: ["telegram", "webhook"] });
  });

  it("works with the typed security and on news alerts", () => {
    expect(parseAlrt([">", "200", "VIA", "EMAIL"], { symbol: "MSFT" })).toMatchObject({ kind: "create", symbol: "MSFT", channels: ["email"] });
    expect(parseAlrt(["NEWS", "WORD", "VIA", "WEBHOOK"])).toEqual({ kind: "createNews", word: "WORD", symbol: null, channels: ["webhook"] });
    expect(parseAlrt(["NEWS", "recall", "aapl", "VIA", "TG"])).toMatchObject({ symbol: "AAPL", channels: ["telegram"] });
  });

  it("no VIA means no channels key at all (every enabled channel)", () => {
    expect(parseAlrt(["AAPL", ">", "200"])).not.toHaveProperty("channels");
    expect(parseAlrt(["NEWS", "recall"])).not.toHaveProperty("channels");
  });

  it("refuses an unknown channel, an empty VIA and VIA on commands that make no alert", () => {
    expect(parseAlrt(["AAPL", ">", "200", "VIA", "SMS"])).toEqual({ kind: "error", message: "UNKNOWN CHANNEL SMS: USE TG, EMAIL OR WEBHOOK" });
    expect(parseAlrt(["AAPL", ">", "200", "VIA"])).toMatchObject({ kind: "error", message: expect.stringContaining("VIA NEEDS CHANNELS") });
    expect(parseAlrt(["DEL", "3", "VIA", "TG"])).toMatchObject({ kind: "error", message: expect.stringContaining("VIA ONLY GOES ON A NEW ALERT") });
    expect(parseAlrt(["AAPL", "VIA", "TG"])).toMatchObject({ kind: "error" }); // the rule is still required
  });

  it("does not take the word via inside a quoted news phrase for the keyword", () => {
    expect(parseAlrt(["NEWS", '"sent', "via", 'email"', "AAPL"])).toEqual({ kind: "createNews", word: "SENT VIA EMAIL", symbol: "AAPL" });
  });

  it("shows the channels as VIA text, blank for the default", () => {
    expect(viaText(["telegram", "email"])).toBe("VIA TG,EMAIL");
    expect(viaText(null)).toBe("");
    expect(viaText([])).toBe("");
  });
});
