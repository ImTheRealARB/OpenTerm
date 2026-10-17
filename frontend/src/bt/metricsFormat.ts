/**
 * BT metrics table rows and formatting (spec decision H: Vibe's calc_metrics set plus VaR / ES 95).
 * Pure: vitest covers it. Values arrive as fractions (0.12 = 12%); null or non-finite shows as a dash.
 */
import { fmtNum, fmtPct, fmtPrice } from "../format";

type Kind = "money" | "signedPct" | "pct" | "ratio" | "times" | "int" | "days";

export interface MetricRow {
  key: string;
  label: string;
  kind: Kind;
  /** Colour by sign (returns) rather than plain text. */
  signed?: boolean;
}

export const METRIC_ROWS: MetricRow[] = [
  { key: "final_value", label: "FINAL VALUE", kind: "money" },
  { key: "total_return", label: "TOTAL RETURN", kind: "signedPct", signed: true },
  { key: "annual_return", label: "ANNUAL RETURN", kind: "signedPct", signed: true },
  { key: "max_drawdown", label: "MAX DRAWDOWN", kind: "signedPct", signed: true },
  { key: "sharpe", label: "SHARPE", kind: "ratio" },
  { key: "sortino", label: "SORTINO", kind: "ratio" },
  { key: "calmar", label: "CALMAR", kind: "ratio" },
  { key: "win_rate", label: "WIN RATE", kind: "pct" },
  { key: "profit_loss_ratio", label: "PROFIT / LOSS RATIO", kind: "ratio" },
  { key: "profit_factor", label: "PROFIT FACTOR", kind: "ratio" },
  { key: "max_consecutive_loss", label: "MAX CONSECUTIVE LOSSES", kind: "int" },
  { key: "avg_holding_days", label: "AVG HOLDING DAYS", kind: "days" },
  { key: "trade_count", label: "TRADES", kind: "int" },
  { key: "benchmark_return", label: "BENCHMARK RETURN", kind: "signedPct", signed: true },
  { key: "excess_return", label: "EXCESS RETURN", kind: "signedPct", signed: true },
  { key: "information_ratio", label: "INFORMATION RATIO", kind: "ratio" },
  { key: "tracking_error", label: "TRACKING ERROR", kind: "pct" },
  { key: "benchmark_beta", label: "BETA", kind: "ratio" },
  { key: "avg_turnover", label: "AVG TURNOVER", kind: "pct" },
  { key: "total_turnover", label: "TOTAL TURNOVER", kind: "times" },
  { key: "var_95", label: "VAR 95 (1 BAR)", kind: "signedPct", signed: true },
  { key: "es_95", label: "ES 95 (1 BAR)", kind: "signedPct", signed: true },
  { key: "unfilled_plan_rejections", label: "UNFILLED ORDERS", kind: "int" },
];

const KIND = new Map(METRIC_ROWS.map((r) => [r.key, r.kind]));

export function fmtMetric(key: string, v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  switch (KIND.get(key)) {
    case "money":
      return fmtPrice(v);
    case "signedPct":
      return fmtPct(v * 100);
    case "pct":
      return fmtNum(v * 100, 2) + "%";
    case "times":
      return fmtNum(v, 2) + "x";
    case "int":
      return fmtNum(v, 0);
    case "days":
      return fmtNum(v, 1);
    default:
      return fmtNum(v, 2);
  }
}
