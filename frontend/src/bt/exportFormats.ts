/** BT EXPORT targets: what each word asks the server for and what the downloaded file is called. */
export interface BtExportFormat {
  /** The server's `fmt` query value. */
  fmt: "csv" | "pine" | "mql5" | "pdf" | "xlsx";
  part?: "trades" | "equity" | "metrics";
  ext: string;
  /** Rule strategies only (Python code cannot be translated faithfully). */
  rulesOnly: boolean;
  /** Binary files come back as bytes, text files as text. */
  binary: boolean;
  mime: string;
}

export const BT_EXPORTS: Record<string, BtExportFormat> = {
  PINE: { fmt: "pine", ext: "pine", rulesOnly: true, binary: false, mime: "text/plain;charset=utf-8" },
  MQL5: { fmt: "mql5", ext: "mq5", rulesOnly: true, binary: false, mime: "text/plain;charset=utf-8" },
  PDF: { fmt: "pdf", ext: "pdf", rulesOnly: false, binary: true, mime: "application/pdf" },
  XLSX: { fmt: "xlsx", ext: "xlsx", rulesOnly: false, binary: true, mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
  TRADES: { fmt: "csv", part: "trades", ext: "csv", rulesOnly: false, binary: false, mime: "text/csv;charset=utf-8" },
  EQUITY: { fmt: "csv", part: "equity", ext: "csv", rulesOnly: false, binary: false, mime: "text/csv;charset=utf-8" },
  METRICS: { fmt: "csv", part: "metrics", ext: "csv", rulesOnly: false, binary: false, mime: "text/csv;charset=utf-8" },
};

export const EXPORT_WORDS = Object.keys(BT_EXPORTS).join("|");

/** File name of a run's export: `BT_<id>.pine`, `BT_<id>.pdf`, `BT_<id>_trades.csv`. */
export function exportFileName(id: string, word: string): string {
  const f = BT_EXPORTS[word.toUpperCase()];
  return f ? `BT_${id}${f.part ? `_${f.part}` : ""}.${f.ext}` : `BT_${id}`;
}

/** The refusal a rule-only format gives for a Python strategy (the server says the same). */
export function rulesOnlyRefusal(word: string): string {
  return `${word.toUpperCase()} EXPORT NEEDS A RULE STRATEGY (PYTHON CODE CANNOT BE TRANSLATED FAITHFULLY; TRADES / EQUITY / METRICS / PDF / XLSX WORK)`;
}
