/**
 * Row keys shared by the Phase 29 filings panels (FTS, MA, BIO; LEGAL opens its rows' pages the same way).
 *   Enter  open FIL for the row's company, filtered to the row's form. FIL lists one company's filings and cannot jump to a single accession,
 *          so the panel's note says so; the ACCESSION column in FIL finds the filing.
 *   O      open the filing itself on sec.gov (or the row's own link).
 * A row with no ticker (an unlisted filer, or the SEC ticker file was down) has no FIL to open: Enter then opens the link and says so.
 */
import { navigate } from "../state/workspace";
import type { TableRow } from "../research/tablePayload";
import { openUrl } from "./secPanel";

export function filingsRowKey(e: KeyboardEvent, panelId: number, row: TableRow | undefined, say: (text: string) => void): boolean {
  if (!row || e.ctrlKey || e.altKey || e.metaKey) return false;
  const ticker = typeof row.ticker === "string" && row.ticker ? row.ticker : null;
  const url = typeof row.url === "string" && row.url ? row.url : null;
  if (e.key === "o" || e.key === "O") {
    if (url) openUrl(url);
    else say("NO LINK FOR THIS ROW");
    return true;
  }
  if (e.key === "Enter") {
    if (ticker) {
      const form = typeof row.form === "string" ? row.form : "";
      navigate(panelId, { fn: "FIL", security: { symbol: ticker }, args: form ? [form] : [] });
    } else if (url) {
      say("NO TICKER FOR THIS FILER: OPENED THE FILING ITSELF (FIL NEEDS A TICKER)");
      openUrl(url);
    } else {
      say("NO TICKER AND NO LINK FOR THIS ROW");
    }
    return true;
  }
  return false;
}
