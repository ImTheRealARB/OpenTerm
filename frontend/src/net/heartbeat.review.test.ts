import { describe, expect, it } from "vitest";
import { heartbeatDead, heartbeatMissed } from "./heartbeat";

describe("review: socket heartbeat (half-open connection never fires close)", () => {
  it("counts a ping interval as missed only when nothing arrived since the previous ping", () => {
    expect(heartbeatMissed(0, 0, 0)).toBe(0); // first ping: nothing to judge yet
    expect(heartbeatMissed(0, 1000, 1004)).toBe(0); // a pong came back
    expect(heartbeatMissed(1, 1000, 1004)).toBe(0); // and clears earlier misses
    expect(heartbeatMissed(0, 1000, 900)).toBe(1); // only older traffic: missed
    expect(heartbeatMissed(1, 6000, 900)).toBe(2);
  });

  it("is dead after two silent intervals in a row, not one", () => {
    expect(heartbeatDead(1)).toBe(false);
    expect(heartbeatDead(2)).toBe(true);
  });

  it("a ping timer that fires once a minute in a background tab does not misfire while traffic arrives", () => {
    let missed = 0;
    let lastPing = 0;
    for (let t = 0; t < 600_000; t += 60_000) {
      missed = heartbeatMissed(missed, lastPing, lastPing + 3); // pong lands 3 ms after each ping
      expect(heartbeatDead(missed)).toBe(false);
      lastPing = t + 1;
    }
  });
});
