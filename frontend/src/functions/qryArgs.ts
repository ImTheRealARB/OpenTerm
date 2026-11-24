/**
 * QRY panel arguments (pure, so vitest can check them). The command line splits on spaces, so the query is the arguments joined
 * back with single spaces; the server parses it (query/lang.py) and answers bad syntax with a message, which the panel shows.
 */
export function qryText(args: string[]): string | null {
  const text = args.join(" ").trim();
  return text ? `QRY ${text}` : null;
}

export const QRY_USAGE =
  "USAGE: QRY <fields> FOR <universe> [WHERE pe<20 AND ...] [SORT f ASC|DESC] [LIMIT n]  |  QRY close FOR AAPL,FRED:DGS10 DATES -1Y..0 [FREQ D|W|M]";
