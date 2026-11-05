import { describe, expect, it } from "vitest";
import type { AlertEngineState } from "../net/api";
import { browserFires, SYNTHETIC_SRC } from "../command/alertArgs";
import { engineView, fmtAge } from "./alertEngineText";

const base: AlertEngineState = {
  running: true,
  note: "ACTIVE WHILE OPENTERM RUNNING",
  watching: ["AAPL", "MSFT"],
  last_tick_age_s: 3.4,
  last_news_poll_age_s: 130,
  fixtures: false,
  skipped: [{ key: "price:2", label: "AAPL > 200", reason: "STALE TICK 300s OLD", age_s: 240 }],
};

describe("engineView", () => {
  it("states the honest limit, what is watched, how fresh the data is and every refused match", () => {
    const v = engineView(base);
    expect(v.cls).toBe("up");
    expect(v.head).toBe("SERVER ALERT ENGINE: ACTIVE WHILE OPENTERM RUNNING");
    expect(v.detail).toBe("WATCHING AAPL, MSFT · LAST TICK 3 s AGO · NEWS CHECKED 2 min AGO");
    expect(v.skipped).toEqual(["AAPL > 200: STALE TICK 300s OLD (4 min ago)"]);
  });

  it("says plainly when there is nothing to watch, no tick yet, or the engine is unknown or stopped", () => {
    const idle = engineView({ ...base, watching: [], last_tick_age_s: null, last_news_poll_age_s: null, skipped: [] });
    expect(idle.detail).toBe("NO PRICE ALERTS TO WATCH · NO TICK YET · NEWS NOT CHECKED YET");
    expect(engineView(null)).toMatchObject({ cls: "err" });
    expect(engineView({ ...base, running: false })).toMatchObject({ cls: "err", head: "SERVER ALERT ENGINE: STOPPED" });
  });

  it("labels fixture mode: the server fires nothing, this tab does", () => {
    const v = engineView({ ...base, fixtures: true });
    expect(v.cls).toBe("warn");
    expect(v.head).toContain("FIXTURE MODE");
  });

  it("formats ages", () => {
    expect([fmtAge(3.4), fmtAge(89), fmtAge(120), fmtAge(7200)]).toEqual(["3 s", "89 s", "2 min", "2 h"]);
  });
});

describe("browserFires (no double notification)", () => {
  it("never fires real ticks in the browser: the server owns them", () => {
    for (const src of ["y", "p", "a", "k"]) expect(browserFires(src.charCodeAt(0), false)).toBe(false);
    expect(browserFires(src2code("y"), null)).toBe(false); // engine state unknown: still not the browser's job
  });

  it("fires labelled SYNTHETIC ticks and, in fixture mode, everything (the server refuses both)", () => {
    expect(browserFires(SYNTHETIC_SRC, false)).toBe(true);
    expect(SYNTHETIC_SRC).toBe("s".charCodeAt(0));
    expect(browserFires(src2code("y"), true)).toBe(true);
  });
});

const src2code = (c: string) => c.charCodeAt(0);
