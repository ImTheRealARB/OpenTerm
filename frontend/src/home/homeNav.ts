/**
 * Keyboard movement on the HOME page (pure; unit-tested).
 * The page is a list of blocks, each with some selectable rows. The cursor is (block, row).
 *   j / Down, k / Up   one row (stops at the ends of the block)
 *   l / Right, h / Left  next / previous block that has rows (wraps round), keeping the row number when it fits
 *   g / Home, G / End  first / last row of the block
 * (Tab would be the natural key between blocks, but Tab is the global next-panel key and never reaches a panel.)
 */
export interface Pos {
  b: number;
  r: number;
}

/** The new cursor for a key, or null when the key is not a movement key. `counts[b]` = selectable rows in block b. */
export function moveNav(counts: readonly number[], pos: Pos, key: string): Pos | null {
  const n = counts.length;
  const clamp = (b: number, r: number): Pos => ({ b, r: Math.max(0, Math.min(r, Math.max(0, counts[b] - 1))) });
  // Next block (dir 1) or previous (dir -1) that has at least one row; stays put when there is none.
  const hop = (dir: 1 | -1): Pos => {
    for (let i = 1; i <= n; i++) {
      const b = (((pos.b + dir * i) % n) + n) % n;
      if (counts[b] > 0) return clamp(b, pos.r);
    }
    return pos;
  };
  switch (key) {
    case "j":
    case "ArrowDown":
      return clamp(pos.b, pos.r + 1);
    case "k":
    case "ArrowUp":
      return clamp(pos.b, pos.r - 1);
    case "l":
    case "ArrowRight":
      return hop(1);
    case "h":
    case "ArrowLeft":
      return hop(-1);
    case "g":
    case "Home":
      return clamp(pos.b, 0);
    case "G":
    case "End":
      return clamp(pos.b, Infinity);
    default:
      return null;
  }
}

/** The first block that has rows (where the cursor starts), or 0. */
export const firstBlock = (counts: readonly number[]): number => Math.max(0, counts.findIndex((c) => c > 0));
