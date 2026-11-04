/**
 * Glossary tips for canvas grid column headers (GUI mode). Lazy chunk: Grid imports it on the first header hover or `T` key,
 * so it costs nothing at startup and nothing in Terminal mode. A pure title -> term lookup plus a thin call into glossaryTip.
 */
import { explain } from "./glossary";
import { hideTip, showTipAt, type Box } from "./glossaryTip";

/** Column titles that are not a glossary key as written. Keys are the title in upper case. */
const ALIAS: Readonly<Record<string, string>> = {
  "MKT CAP": "MARKET CAP",
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
