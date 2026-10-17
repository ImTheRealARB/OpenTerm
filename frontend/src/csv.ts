/** CSV export from any column set: what you see is what you get (formatted cells). */
import { csvFileName, toCsv, type CsvCell } from "./csvText";

export function downloadCsv(name: string, header: string[], rows: CsvCell[][]): string {
  const file = csvFileName(name);
  // BOM so spreadsheet apps read UTF-8 names (e.g. "Société Générale") correctly.
  const url = URL.createObjectURL(new Blob(["﻿", toCsv(header, rows)], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = file;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return file;
}
