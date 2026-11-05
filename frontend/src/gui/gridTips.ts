/**
 * Glossary tips for canvas grid column headers (GUI mode). Lazy chunk: Grid imports it on the first header hover or `T` key,
 * so it costs nothing at startup and nothing in Terminal mode. A pure title -> term lookup plus a thin call into glossaryTip.
 */
import { explain } from "./glossary";
import { headerHit } from "../components/gridHeaderHit";
import { hideTip, showTipAt, type Box } from "./glossaryTip";

/** Column titles that are not a glossary key as written. Keys are the title in upper case. */
const ALIAS: Readonly<Record<string, string>> = {
  "MKT CAP": "MARKET CAP",
  // GUI header words of the quote grids (functions/quoteRows.ts guiTitle) and the glossary entry each one explains.
  "PRICE": "LAST",
  "CHANGE %": "CHANGE",
  "%CHG": "CHANGE",
  "% CHG": "CHANGE",
  "CHG%": "CHANGE",
  "CHG": "CHANGE",
  "DAY CHG": "DAY CHANGE",
  "VOL": "VOLUME",
  "24H VOL": "VOLUME",
  "YLD": "YIELD",
  "YIELD %": "YIELD",
  "DIV YLD": "DIVIDEND YIELD",
  "ADJ CLOSE": "ADJUSTED CLOSE",
  "MKT VAL": "MARKET VALUE",
  "UNRL P&L": "UNREALISED GAIN",
  "UNRL %": "UNREALISED GAIN",
  "MAX DD": "MAX DRAWDOWN",
  "WIN": "WIN RATE",
  "1Y RANGE": "52-WEEK RANGE",
  "1Y HIGH": "52-WEEK RANGE",
  "1Y LOW": "52-WEEK RANGE",
  "24H HIGH": "HIGH",
  "24H LOW": "LOW",
  "BID QTY": "BID",
  "ASK QTY": "ASK",
  "B - A": "SPREAD",
};

/** The glossary term for a column title, or "" when there is none. */
export function termForColumn(title: string): string {
  const t = title.trim().toUpperCase();
  const k = ALIAS[t] ?? t;
  return explain(k) ? k : "";
}

/** Indexes of the columns that have a glossary entry. */
export function glossaryColumns(titles: readonly string[]): number[] {
  const out: number[] = [];
  titles.forEach((t, i) => {
    if (termForColumn(t)) out.push(i);
  });
  return out;
}

/** Show the tip for a header cell. `cell` is its screen rect, `panel` the element holding the grid. */
export function showColumnTip(title: string, cell: Box, panel: Element | null): void {
  const term = termForColumn(title);
  if (!term) return hideTip();
  showTipAt(term, cell, panel?.getBoundingClientRect() ?? cell);
}

export { hideTip };

/** What Grid hands over: its hover state and geometry (the tip logic lives here so the startup bundle stays small). */
export interface TipCtx {
  tip: { at: number; i: number; hasTips: boolean | null };
  cv: HTMLCanvasElement;
  xs: readonly number[];
  cw: number;
  pad: number;
  rowH: number;
  cols: readonly { title: string; width: number }[];
  panel: Element | null;
}

const cell = (k: TipCtx, c: number): Box => {
  const r = k.cv.getBoundingClientRect();
  return { left: r.left + k.xs[c], top: r.top, right: r.left + k.xs[c] + k.cols[c].width * k.cw + k.pad * 2, bottom: r.top + k.rowH };
};

/** Mouse moved over the grid canvas: show or hide the tip for the header cell under it. */
export function headerMove(e: MouseEvent, k: TipCtx): void {
  const r = k.cv.getBoundingClientRect();
  const n = k.xs.length;
  const y = e.clientY - r.top;
  const c = y >= 0 && y < k.rowH && n ? headerHit(e.clientX - r.left, k.xs, k.xs[n - 1] + k.cols[n - 1].width * k.cw + k.pad * 2) : -1;
  if (c === k.tip.at) return;
  k.tip.at = c;
  if (c < 0 || !k.cols[c]) hideTip();
  else showColumnTip(k.cols[c].title, cell(k, c), k.panel);
}

export function headerLeave(k: TipCtx): void {
  k.tip.at = -1;
  hideTip();
}

/** Shift+T: step to the next column that has a glossary line. */
export function nextTip(k: TipCtx): void {
  const cols = glossaryColumns(k.cols.map((c) => c.title));
  k.tip.hasTips = cols.length > 0;
  if (!cols.length) return;
  const c = cols.find((x) => x > k.tip.i) ?? cols[0];
  k.tip.i = c;
  showColumnTip(k.cols[c].title, cell(k, c), k.panel);
}
