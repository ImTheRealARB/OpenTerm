/**
 * Bitsets on a Uint32Array.
 *
 * A bitset stores one yes/no flag per index in a single bit: 32 flags per array element ("word").
 * Flag `i` lives in word `i >>> 5` (i / 32, rounded down) at bit `i & 31` (i mod 32).
 * Compared with a Set<number> or boolean[]: 32x smaller, no hashing, no allocation per flag, and
 * "clear everything" is one `fill(0)` over a few words.
 *
 * These helpers take the words array as an argument so callers can keep (and grow) their own buffers.
 */

/** Number of 32-bit words needed to hold `nbits` flags. */
export const bitWords = (nbits: number): number => (nbits + 31) >>> 5;

export const bitSet = (w: Uint32Array, i: number): void => {
  w[i >>> 5] |= 1 << (i & 31);
};

export const bitClear = (w: Uint32Array, i: number): void => {
  w[i >>> 5] &= ~(1 << (i & 31));
};

/** True if flag `i` is on. Out-of-range indexes read as off (a typed array returns undefined, `undefined & x` is 0). */
export const bitHas = (w: Uint32Array, i: number): boolean => ((w[i >>> 5] >>> (i & 31)) & 1) === 1;

/** A new bitset able to hold at least `nbits` flags, with the old contents copied in. */
export function bitGrow(w: Uint32Array, nbits: number): Uint32Array {
  const need = bitWords(nbits);
  if (w.length >= need) return w;
  const out = new Uint32Array(Math.max(need, w.length * 2));
  out.set(w);
  return out;
}
