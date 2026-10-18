import { afterEach, describe, expect, it } from "vitest";
import { MARKETS, basisOf, clearClosures, closed, dayKind, isOpen, lightOf, setClosures } from "./hours";

const ny = MARKETS.find((m) => m.code === "NY")!;
const tk = MARKETS.find((m) => m.code === "TK")!;
const ln = MARKETS.find((m) => m.code === "LN")!;

afterEach(() => clearClosures());

describe("market hours", () => {
  it("NYSE open midday Wednesday, closed weekend", () => {
    expect(isOpen(ny, new Date("2026-10-14T16:00:00Z"))).toBe(true); // 12:00 ET
    expect(isOpen(ny, new Date("2026-10-14T21:00:00Z"))).toBe(false); // 17:00 ET
    expect(isOpen(ny, new Date("2026-10-17T16:00:00Z"))).toBe(false); // Saturday
  });
  it("Tokyo lunch break is closed", () => {
    expect(isOpen(tk, new Date("2026-10-14T03:00:00Z"))).toBe(false); // 12:00 JST
    expect(isOpen(tk, new Date("2026-10-14T01:00:00Z"))).toBe(true); // 10:00 JST
  });
});

describe("exchange holidays", () => {
  it("a holiday closes the market all day and shows HOL, not CLOSED", () => {
    setClosures("NY", 2026, ["2026-11-26"], ["2026-11-27"], "rules");
    const thanksgiving = new Date("2026-11-26T16:00:00Z"); // 11:00 ET
    expect(closed(ny, thanksgiving)).toBe(true);
    expect(dayKind(ny, thanksgiving)).toBe("HOL");
    expect(isOpen(ny, thanksgiving)).toBe(false);
    expect(lightOf(ny, thanksgiving)).toBe("hol");
    expect(lightOf(ny, new Date("2026-11-25T16:00:00Z"))).toBe("open");
  });

  it("an early-close day closes at 13:00 ET and shows EARLY while open", () => {
    setClosures("NY", 2026, ["2026-11-26"], ["2026-11-27"], "rules");
    expect(isOpen(ny, new Date("2026-11-27T17:30:00Z"))).toBe(true); // 12:30 ET
    expect(lightOf(ny, new Date("2026-11-27T17:30:00Z"))).toBe("early");
    expect(isOpen(ny, new Date("2026-11-27T18:30:00Z"))).toBe(false); // 13:30 ET: closed early
    expect(lightOf(ny, new Date("2026-11-27T18:30:00Z"))).toBe("closed");
  });

  it("a weekend holiday still reads CLOSED, and the date is the exchange's local date", () => {
    setClosures("NY", 2026, ["2026-07-04"], [], "rules"); // never a real NYSE date, but proves the weekend rule
    expect(lightOf(ny, new Date("2026-07-04T16:00:00Z"))).toBe("closed");
    setClosures("TK", 2026, ["2026-11-03"], [], "public");
    expect(closed(tk, new Date("2026-11-02T16:00:00Z"))).toBe(true); // 01:00 JST on the 3rd although it is still the 2nd in UTC
    expect(closed(tk, new Date("2026-11-03T16:00:00Z"))).toBe(false); // 01:00 JST on the 4th
  });

  it("with no holiday data loaded nothing is guessed", () => {
    expect(closed(ny, new Date("2026-11-26T16:00:00Z"))).toBe(false);
    expect(dayKind(ny, new Date("2026-11-26T16:00:00Z"))).toBeNull();
    expect(basisOf(ny, new Date("2026-11-26T16:00:00Z"))).toBeNull();
    expect(isOpen(ny, new Date("2026-11-26T16:00:00Z"))).toBe(true); // weekday session only, as before
  });

  it("the basis says where the dates came from; a different year is not covered", () => {
    setClosures("LN", 2026, ["2026-12-25"], [], "public");
    expect(basisOf(ln, new Date("2026-12-01T12:00:00Z"))).toBe("public");
    expect(basisOf(ln, new Date("2027-01-04T12:00:00Z"))).toBeNull();
  });
});
