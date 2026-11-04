/**
 * Heikin Ashi ("average bar") candles: a smoothed version of the normal OHLC bars that makes trends easier to see.
 *   close = (o + h + l + c) / 4
 *   open  = midpoint of the PREVIOUS Heikin Ashi bar's open and close (the first bar uses its own open and close)
 *   high  = highest of the real high, the new open and the new close
 *   low   = lowest of the real low, the new open and the new close
 * Pure function, so vitest can check it.
 */
export function heikinAshi(o: ArrayLike<number>, h: ArrayLike<number>, l: ArrayLike<number>, c: ArrayLike<number>): { o: number[]; h: number[]; l: number[]; c: number[] } {
  const n = c.length;
  const out = { o: new Array<number>(n), h: new Array<number>(n), l: new Array<number>(n), c: new Array<number>(n) };
  for (let i = 0; i < n; i++) {
    const hc = (o[i] + h[i] + l[i] + c[i]) / 4;
    const ho = i === 0 ? (o[i] + c[i]) / 2 : (out.o[i - 1] + out.c[i - 1]) / 2;
    out.c[i] = hc;
    out.o[i] = ho;
    out.h[i] = Math.max(h[i], ho, hc);
    out.l[i] = Math.min(l[i], ho, hc);
  }
  return out;
}
