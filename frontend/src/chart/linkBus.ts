/**
 * Chart sync inside a link group (Phase 22): one GP chart says where its crosshair is, which dates it shows or which candle
 * length it uses, and every other GP chart of the same group follows (each part switched in SETTINGS LINK). A plain
 * in-page publish / subscribe: no store, no React. `from` is the sending panel, so a chart never reacts to itself.
 */
export type LinkMsg =
  | { group: string; from: number; kind: "cross"; t: number | null }
  | { group: string; from: number; kind: "range"; a: number; b: number }
  | { group: string; from: number; kind: "interval"; interval: string | undefined };

const subs = new Set<(m: LinkMsg) => void>();

export function publishLink(m: LinkMsg): void {
  for (const fn of subs) fn(m);
}

export function onLink(fn: (m: LinkMsg) => void): () => void {
  subs.add(fn);
  return () => {
    subs.delete(fn);
  };
}
