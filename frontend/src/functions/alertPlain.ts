import type { Alert, NewsAlert } from "../net/api";

/**
 * GUI wording for one alert, a plain sentence instead of command syntax (pure, unit-tested):
 * "Alert when AAPL goes above 200", "Alert when TSLA moves down more than 3% in a day", "Alert when news mentions "recall" for AAPL".
 */
export function plainAlert(a: Alert | null, n: NewsAlert | null): string {
  if (n) return `Alert when news mentions "${n.word}" ${n.symbol ? `for ${n.symbol}` : "in the top stories"}`;
  if (!a) return "";
  if (a.unit === "pct") return `Alert when ${a.symbol} moves ${a.op === ">" ? "up" : "down"} more than ${Math.abs(a.value)}% in a day`;
  return `Alert when ${a.symbol} goes ${a.op === ">" ? "above" : "below"} ${a.value}`;
}

