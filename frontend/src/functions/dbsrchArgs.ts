/**
 * DBSRCH: pure argument and text helpers (no DOM, no network; vitest runs them).
 *
 * The panel has two steps and keeps its whole state in the command's args, so the global Back key returns to the same page:
 *   DBSRCH <words>                              step 1: datasets that match the words
 *   DBSRCH DS:<PROVIDER>/<DATASET> [words]      step 2: the series of one dataset that match the words
 *   ... OFFSET:<n>                              paging: skip the first n rows (the server shows 20 datasets or 30 series per page)
 * `DS:` and `OFFSET:` may stand anywhere among the words.
 */

/** Rows per page the server asks DBnomics for (backend/openterm/providers/worldstats.py DBN_DATASET_PAGE / DBN_SERIES_PAGE). */
export const DATASET_PAGE = 20;
export const SERIES_PAGE = 30;

// Same shape as the backend's `dbsearch.DATASET_REF`: dataset codes may hold `.`, `:` and `@` (OECD: DSD_TAXBEN_NRR@DF_NRR).
const DS = /^DS:([A-Za-z0-9_-]+)\/([A-Za-z0-9_.:@-]+)$/i;
const OFFSET = /^OFFSET:(\d{1,6})$/i;

export const DBSRCH_USAGE = "USAGE: DBSRCH <WORDS> (E.G. DBSRCH FRANCE INFLATION) OR DBSRCH DS:<PROVIDER>/<DATASET> [WORDS]";

export interface DbsrchArgs {
  /** The search words, single-spaced; may be empty only when a dataset is given. */
  q: string;
  /** `PROVIDER/DATASET` (provider upper-cased, dataset exactly as typed: Eurostat codes are lower case) or "" for the dataset search. */
  dataset: string;
  offset: number;
  error: string | null;
}

export function parseDbsrchArgs(args: string[]): DbsrchArgs {
  const words: string[] = [];
  let dataset = "";
  let offset = 0;
  for (const a of args.filter(Boolean)) {
    const ds = DS.exec(a);
    const off = OFFSET.exec(a);
    if (ds) dataset = `${ds[1].toUpperCase()}/${ds[2]}`;
    else if (off) offset = Number(off[1]);
    else words.push(a);
  }
  const q = words.join(" ");
  if (!dataset && q.length < 2) return { q, dataset, offset, error: "GIVE SEARCH WORDS. " + DBSRCH_USAGE };
  if (dataset && q && q.length < 2) return { q, dataset, offset, error: "SEARCH WORDS NEED 2+ CHARACTERS. " + DBSRCH_USAGE };
  return { q, dataset, offset, error: null };
}

/** The args that reproduce a state; the inverse of `parseDbsrchArgs`. An offset of 0 is left out. */
export function buildDbsrchArgs(p: { q: string; dataset: string; offset: number }): string[] {
  const out: string[] = [];
  if (p.dataset) out.push(`DS:${p.dataset}`);
  if (p.q) out.push(...p.q.split(/\s+/).filter(Boolean));
  if (p.offset > 0) out.push(`OFFSET:${p.offset}`);
  return out;
}

/** "1-20 OF 90" for the rows on screen; "NO MATCH" when the API found nothing. `shown` is the number of rows actually on this page. */
export function pageText(offset: number, shown: number, total: number): string {
  if (total <= 0 || shown <= 0) return "NO MATCH";
  return `${offset + 1}-${offset + shown} OF ${total}`;
}

/** Whether another page exists after this one. */
export function hasNext(offset: number, shown: number, total: number): boolean {
  return shown > 0 && offset + shown < total;
}

/** The offset of the page before this one (never below 0), or null when this is the first page. */
export function prevOffset(offset: number, page: number): number | null {
  return offset <= 0 ? null : Math.max(0, offset - page);
}

/** A count that may be unknown: "" when the API gave none. */
export function count(n: number | null | undefined): string {
  return n == null ? "" : n.toLocaleString("en-US");
}
