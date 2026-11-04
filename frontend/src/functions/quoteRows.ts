/**
 * Shared by the live quote grids (Q, WL, WEI, FX, CMDTY): REST snapshot, then WebSocket ticks
 * repaint only the rows that changed, plus the common columns and grid navigation keys.
 */
import { useEffect, useRef, useState, type RefObject } from "react";
import type { CellColor, Column, GridHandle } from "../components/Grid";
import { fmtAge, fmtBig, fmtChg, fmtPct, fmtPrice, fmtTime, sign } from "../format";
import { ApiError, api, type Quote, type QuoteResult } from "../net/api";
import { subscribe } from "../net/socket";
import { NO_SYM, symId } from "../state/symbols";
import { hasLive, live, onTicks, SRC_SYNTHETIC, srcLabel } from "../state/ticks";
import { buildRowIndex, markHits, rowIds, startAgeRedraw, subscriptionKey, symbolLayout } from "./liveRowsCore";

export interface QRow {
  input: string;
  symbol: string;
  q?: Quote;
  stale?: boolean;
  fetchedAt: number;
  ageAtFetch: number;
  error?: string;
  /** Interned symbol id, filled in lazily by `rowId`. */
  sid?: number;
}

// --- Live reads by integer id ----------------------------------------------------------------------------------
// A grid row used to look its symbol up in a Map on EVERY cell paint. Now the row carries its interned id (`sid`, filled in
// once, the first time the row is painted) and a cell reads the typed array `live.price[id]` directly.

/** The row's interned symbol id (NO_SYM for rows with no symbol: section headers). Cached on the row itself. */
export function rowId(r: QRow): number {
  return r.sid ?? (r.sid = r.symbol ? symId(r.symbol) : NO_SYM);
}

/** `column[id]` as number-or-null when the symbol has live data (NaN means "the tick did not carry this field"). */
function liveNum(column: Float64Array, id: number): number | null {
  if (!hasLive(id)) return null;
  const v = column[id];
  return v === v ? v : null;
}

export const price = (r: QRow) => {
  const id = rowId(r);
  return hasLive(id) ? live.price[id] : (r.q?.price ?? null);
};
export const pct = (r: QRow) => liveNum(live.pct, rowId(r)) ?? r.q?.change_pct ?? null;
export const chg = (r: QRow) => liveNum(live.change, rowId(r)) ?? r.q?.change ?? null;
export const vol = (r: QRow) => liveNum(live.volume, rowId(r)) ?? r.q?.volume ?? null;
export const high = (r: QRow) => liveNum(live.high, rowId(r)) ?? r.q?.high ?? null;
export const low = (r: QRow) => liveNum(live.low, rowId(r)) ?? r.q?.low ?? null;
export const dirColor = (v: number | null): CellColor => (sign(v) > 0 ? "up" : sign(v) < 0 ? "down" : "val");
export const quoteTime = (r: QRow) => {
  const id = rowId(r);
  return hasLive(id) ? live.t[id] : r.q?.market_time ? r.q.market_time * 1000 : null;
};

export function srcText(r: QRow): string {
  const id = rowId(r);
  if (hasLive(id)) return srcLabel(live.src[id]);
  if (r.error || !r.q) return "";
  const age = r.ageAtFetch + (Date.now() - r.fetchedAt) / 1000;
  return r.stale ? `STALE ${fmtAge(age)}` : (r.q.source ?? "").toUpperCase();
}

export function srcColor(r: QRow): CellColor {
  const id = rowId(r);
  if (hasLive(id)) return live.src[id] === SRC_SYNTHETIC ? "warn" : "up";
  return r.stale ? "warn" : "dim";
}

export const lastColor = (r: QRow): CellColor => {
  const id = rowId(r);
  return hasLive(id) ? dirColor(live.dir[id]) : "val";
};
export const lastFlash = (r: QRow, f: number): CellColor | null => {
  const id = rowId(r);
  if (!hasLive(id) || live.frame[id] !== f) return null;
  const d = live.dir[id];
  return d > 0 ? "up" : d < 0 ? "down" : null;
};

export const QUOTE_COLUMNS: Column<QRow>[] = [
  { title: "SECURITY", width: 11, text: (r) => r.symbol, color: (r) => (r.error ? "err" : "fg") },
  { title: "SRC", width: 9, text: srcText, color: srcColor },
  { title: "NAME", width: 14, text: (r) => r.error ?? r.q?.name ?? "", color: (r) => (r.error ? "err" : "dim") },
  { title: "LAST", width: 12, align: "right", text: (r) => fmtPrice(price(r)), color: lastColor, flash: lastFlash },
  { title: "CHG", width: 10, align: "right", text: (r) => fmtChg(chg(r)), color: (r) => dirColor(chg(r)) },
  { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(pct(r)), color: (r) => dirColor(pct(r)) },
  { title: "VOLUME", width: 9, align: "right", text: (r) => fmtBig(vol(r)) },
  { title: "HIGH", width: 11, align: "right", text: (r) => fmtPrice(high(r)) },
  { title: "LOW", width: 11, align: "right", text: (r) => fmtPrice(low(r)) },
  { title: "TIME", width: 8, align: "right", text: (r) => fmtTime(quoteTime(r)) },
  { title: "CCY", width: 4, text: (r) => r.q?.currency ?? "", color: () => "dim" },
];

/** GUI mode: a wider NAME column, so a row's error text ("NO DATA FOR SYMBOL") is not cut off. Terminal keeps QUOTE_COLUMNS. */
export const QUOTE_COLUMNS_GUI: Column<QRow>[] = QUOTE_COLUMNS.map((c) => (c.title === "NAME" ? { ...c, width: 24 } : c));

export const SORTS = ["INPUT", "SYMBOL", "%CHG", "VOLUME"] as const;
export type Sort = (typeof SORTS)[number];

/** Sorted once, on request: live re-sorting on every tick would make rows jump under the cursor. */
export function sortRows(rows: QRow[], by: Sort, inputs: string[]): QRow[] {
  const key = (r: QRow) => (by === "%CHG" ? -(pct(r) ?? -Infinity) : by === "VOLUME" ? -(vol(r) ?? -Infinity) : 0);
  if (by === "INPUT") return inputs.map((i) => rows.find((r) => r.input === i)).filter((r): r is QRow => !!r);
  if (by === "SYMBOL") return [...rows].sort((x, y) => x.symbol.localeCompare(y.symbol));
  return [...rows].sort((x, y) => key(x) - key(y));
}

export const liveSymbol = (r: QRow) => (r.error ? undefined : r.symbol);

export const blankRow = (input: string): QRow => ({ input, symbol: input, fetchedAt: Date.now(), ageAtFetch: 0 });

function toRow(input: string, r: QuoteResult | undefined, now: number): QRow {
  if (!r) return { input, symbol: input, fetchedAt: now, ageAtFetch: 0, error: "NO DATA FOR SYMBOL" };
  if ("error" in r) return { input, symbol: r.symbol ?? input, fetchedAt: now, ageAtFetch: 0, error: r.error };
  return { input, symbol: r.data.symbol, q: r.data, stale: r.stale, fetchedAt: now, ageAtFetch: r.age_s };
}

const CHUNK = 200; // the backend's per-request symbol cap

/** REST snapshot of `inputs` (any length), re-fetched when `inputs` or `reload` change. */
export function useQuotes(inputs: string[], reload: number) {
  const [rows, setRows] = useState<QRow[]>(() => inputs.map(blankRow));
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    if (!inputs.length) {
      setRows([]);
      setLoading(false);
      return;
    }
    const chunks = Array.from({ length: Math.ceil(inputs.length / CHUNK) }, (_, i) => inputs.slice(i * CHUNK, (i + 1) * CHUNK));
    Promise.all(chunks.map((c) => api.quotes(c)))
      .then((parts) => {
        if (!alive) return;
        const results = Object.assign({}, ...parts.map((p) => p.results)) as Record<string, QuoteResult>;
        const now = Date.now();
        setRows(inputs.map((input) => toRow(input, results[input], now)));
      })
      .catch((e: ApiError) => {
        if (alive) setRows(inputs.map((s) => ({ ...blankRow(s), error: e.message })));
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [inputs, reload]);
  return { rows, setRows, loading };
}

/**
 * One subscription for the symbols in `rows`; ticks repaint only their rows.
 * Per frame: the tick batch lists the ids that ticked; `markHits` walks each id's row chain in a flat index and sets a bit per
 * row in a "dirty rows" bitset; the grid then repaints only the dirty rows that are on screen. No arrays or closures per frame.
 */
export function useLiveRows<R>(rows: R[], grid: RefObject<GridHandle | null>, symbolOf: (r: R) => string | undefined) {
  const names = symbolLayout(rows, symbolOf);
  const key = subscriptionKey(names);
  useEffect(() => (key ? subscribe(key.split(",")) : undefined), [key]);

  // The row index is rebuilt whenever `rows` changes (a REST refresh, a sort): a few typed-array writes, cheaper than comparing layouts.
  useEffect(() => {
    const index = buildRowIndex(rowIds(names));
    return onTicks((batch, frame) => {
      if (markHits(index, batch.ids, batch.count) > 0) grid.current?.redrawDirty(index.dirty, frame);
    });
  }, [rows, grid]); // eslint-disable-line react-hooks/exhaustive-deps -- `names` is derived from `rows`

  // AGE/STALE text keeps counting, but not while the tab is hidden; one redraw when it comes back.
  useEffect(() => startAgeRedraw(() => grid.current?.redraw(), 5000, typeof document === "undefined" ? undefined : document), [grid]);
}

/** j/k, arrows, g/G, Home/End, PageUp/PageDown. `skip(i)` rows (section headers) are stepped over. */
export function navKey(e: KeyboardEvent, g: GridHandle | null, count: number, skip?: (i: number) => boolean): boolean {
  if (!g) return false;
  const step = (d: 1 | -1) => {
    const before = g.selected();
    g.move(d);
    const at = g.selected();
    if (skip?.(at)) {
      g.move(d);
      if (skip(g.selected())) g.moveTo(before); // a header at the very end: stay put
    }
  };
  switch (e.key) {
    case "j":
    case "ArrowDown":
      step(1);
      return true;
    case "k":
    case "ArrowUp":
      step(-1);
      return true;
    case "g":
    case "Home":
      g.moveTo(skip?.(0) ? 1 : 0);
      return true;
    case "G":
    case "End":
      g.moveTo(count - 1);
      return true;
    case "PageDown":
      g.page(1);
      return true;
    case "PageUp":
      g.page(-1);
      return true;
  }
  return false;
}

/** A ref that always holds the latest value, for key handlers registered once per mount. */
export function useLatest<T>(value: T) {
  const r = useRef(value);
  r.current = value;
  return r;
}
