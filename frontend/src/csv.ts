/** CSV export from any column set: what you see is what you get (formatted cells). */
import { csvFileName, toCsv, type CsvCell } from "./csvText";

/** Saves a table as a CSV file (UTF-8 with a byte-order mark so spreadsheet apps read it right); returns the file name. */
export function downloadCsv(name: string, header: string[], rows: CsvCell[][]): string {
  return downloadText(csvFileName(name), toCsv(header, rows), { type: "text/csv;charset=utf-8", bom: true });
}

/**
 * Saves text (a Pine script, a server-built CSV) as a file; returns the file name. The one download helper: CSV callers pass
 * `type: "text/csv;charset=utf-8"` and `bom: true`.
 *  - `type`: the file's MIME type (plain text by default).
 *  - `bom`: put a UTF-8 byte-order mark (U+FEFF) before the text. Excel and other spreadsheet apps need it to read non-ASCII
 *    names (e.g. "Societe Generale" with accents) as UTF-8 instead of guessing a legacy code page. Off by default: a Pine script does not want it.
 */
export function downloadText(file: string, text: string, opts: { type?: string; bom?: boolean } = {}): string {
  const { type = "text/plain;charset=utf-8", bom = false } = opts;
  return downloadBlob(file, new Blob(bom ? ["﻿", text] : [text], { type }));
}

/** Saves a binary file (a PDF report, an XLSX workbook); returns the file name. */
export function downloadBlob(file: string, blob: Blob): string {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = file;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return file;
}
