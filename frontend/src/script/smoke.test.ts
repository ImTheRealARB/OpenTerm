import { describe, expect, it } from "vitest";
import { compile } from "./index";

const bars = (c: number[]) => ({
  o: c.slice(),
  h: c.map((x) => x + 1),
  l: c.map((x) => x - 1),
  c: c.slice(),
  v: c.map(() => 100),
  t: c.map((_, i) => 1_700_000_000 + i * 86400),
});

describe("smoke", () => {
  it("runs a simple script", () => {
    const r = compile(`indicator("x")
a = close * 2
plot(a, "A")
`);
    if (!r.ok) throw new Error(JSON.stringify(r.errors));
    const run = r.program.run(bars([1, 2, 3, 4]));
    const res = run.result();
    expect(res.error).toBeUndefined();
    expect(Array.from(res.plots[0].values as Float64Array)).toEqual([2, 4, 6, 8]);
  });
});
