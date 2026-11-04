import type { Cols } from "./types";

/** Deterministic synthetic OHLCV (LCG noise on a wave), 400 bars. */
export function synth(n = 400): Cols {
  let s = 12345;
  const rnd = () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296);
  const o = new Float64Array(n);
  const h = new Float64Array(n);
  const l = new Float64Array(n);
  const c = new Float64Array(n);
  const v = new Float64Array(n);
  const t = new Float64Array(n);
  let p = 100;
  for (let i = 0; i < n; i++) {
    const open = p;
    p = Math.max(5, p + Math.sin(i / 17) * 0.8 + (rnd() - 0.5) * 3);
    o[i] = open;
    c[i] = p;
    h[i] = Math.max(open, p) + rnd() * 1.5 + 0.05;
    l[i] = Math.min(open, p) - rnd() * 1.5 - 0.05;
    v[i] = 1000 + Math.floor(rnd() * 5000);
    t[i] = 1_700_000_000 + i * 86400;
  }
  return { o, h, l, c, v, t };
}
