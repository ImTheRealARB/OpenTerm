/**
 * TRA: total return of one or more securities over a period, against a benchmark (default SPY).
 *
 *   TRA AAPL 5Y                       price return, dividends, total return, annualised return, benchmark, excess
 *   TRA AAPL,MSFT,NVDA 3Y VS ^NSEI    up to 12 securities, one row each
 *
 * The server does the maths on daily adjusted closes (`/api/world/tra`); this panel only shows the answer. A source with no
 * adjusted close can give a price return only: that row says PRICE (never a made-up total return). Nothing here is a forecast.
 * Keys: J/K move, R next range, E CSV, F5 refresh.
 */
import { useEffect, useMemo, useRef } from "react";
import { ChartView, type ChartHandle } from "../chart/ChartView";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { returnsApi } from "../net/returnsApi";
import type { TraPayload, TraRow } from "../net/returnsTypes";
import { replaceView } from "../state/workspace";
import { useLatest } from "../state/useLatest";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { usePanelRefresh } from "./panelRefresh";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { dayToEpoch, datedBars, nextRange, num, parseTraArgs, signClass, signedPct, traViewArgs } from "./traBeta";
import "./traBeta.css";
import { useEnvelope } from "./useEnvelope";

/** One table line: a security's row, or the benchmark's (flagged so its symbol reads "SPY (BENCH)"). */
interface Line extends TraRow {
  isBench?: boolean;
}

const COLUMNS: Column<Line>[] = [
  { title: "SECURITY", width: 14, text: (r) => (r.isBench ? `${r.symbol} (BENCH)` : r.symbol), color: (r) => (r.error ? "err" : r.isBench ? "dim" : "acc") },
  { title: "BASIS", width: 6, text: (r) => r.basis ?? "—", color: (r) => (r.basis === "PRICE" ? "warn" : "dim") },
  { title: "FROM", width: 10, text: (r) => r.first ?? "—", color: () => "dim" },
  { title: "TO", width: 10, text: (r) => r.last ?? "—", color: () => "dim" },
  { title: "DAYS", width: 6, align: "right", text: (r) => (r.days == null ? "—" : String(r.days)), color: () => "dim" },
  { title: "PRICE", width: 9, align: "right", text: (r) => signedPct(r.price_return_pct), color: (r) => signClass(r.price_return_pct) as CellColor },
  { title: "DIVS", width: 8, align: "right", text: (r) => signedPct(r.dividend_part_pct), color: () => "dim" },
  { title: "TOTAL", width: 9, align: "right", text: (r) => signedPct(r.total_return_pct), color: (r) => signClass(r.total_return_pct) as CellColor },
  { title: "ANNUAL", width: 9, align: "right", text: (r) => signedPct(r.annualised_pct), color: (r) => signClass(r.annualised_pct) as CellColor },
  { title: "BENCH", width: 9, align: "right", text: (r) => signedPct(r.bench_return_pct), color: () => "dim" },
  { title: "EXCESS", width: 9, align: "right", text: (r) => signedPct(r.excess_pct), color: (r) => signClass(r.excess_pct) as CellColor },
  { title: "NOTE", width: 44, text: (r) => noteOf(r), color: (r) => (r.error ? "err" : "warn") },
];

/** The small print of a row: why it has no numbers, or which basis a number is on when that is not the full total return. */
function noteOf(r: Line): string {
  if (r.error) return r.error;
  const notes: string[] = [];
  if (r.basis === "PRICE") notes.push("PRICE ONLY, NO DIVIDEND DATA");
  else if (r.excess_basis === "PRICE") notes.push("EXCESS ON PRICE RETURNS");
  return notes.join(" · ");
}

export default function TRA({ panelId, security, args }: FunctionProps) {
  // With no symbol typed, the panel's own security is used. A usage error is shown and nothing is fetched.
  const parsed = useMemo(() => parseTraArgs(args, security?.symbol), [args, security?.symbol]);
  if (parsed.error) {
    return (
      <div className="fn">
        <div className="line">
          <span className="acc">TRA</span> TOTAL RETURN
        </div>
        <div className="err">{parsed.error}</div>
      </div>
    );
  }
  return <TraView panelId={panelId} symbols={parsed.symbols} vs={parsed.vs} range={parsed.range} />;
}

function TraView({ panelId, symbols, vs, range }: { panelId: number; symbols: string[]; vs: string; range: string }) {
  const grid = useRef<GridHandle>(null);
  const chart = useRef<ChartHandle>(null);
  // The key names what is loaded: a new symbol list, benchmark or range is a new load (the old answer is dropped).
  const key = `${symbols.join(",")}|${vs}|${range}`;
  const { env, error, loading, reload } = useEnvelope<TraPayload>(key, (fresh) => returnsApi.tra(symbols, vs, range, fresh));
  usePanelRefresh(panelId, () => { void reload(true); });

  const d = env?.data;
  const rows = useMemo<Line[]>(() => (d ? [...d.rows, { ...d.benchmark, isBench: true }] : []), [d]);
  const latest = useLatest({ rows, symbols, vs, range });
  useCsvExport(panelId, () => (d ? gridCsv(`TRA_${range}_${symbols.join("_")}`, COLUMNS, rows) : null));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (navKey(e, grid.current, latest.current.rows.length)) return true;
        if (e.key === "r" || e.key === "R") {
          // R = the next range. The new range goes into the view's args so a saved layout reopens on it.
          const s = latest.current;
          replaceView(panelId, (v) => ({ ...v, args: traViewArgs({ symbols: s.symbols, vs: s.vs, range: nextRange(s.range) }) }));
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  // The two rebased lines for the chart (both start at 100 on the first date they share). Dates arrive as text.
  const bars = useMemo(() => {
    const c = d?.chart;
    if (!c) return null;
    return {
      main: datedBars(c.symbol_a, c.dates, c.a),
      other: { symbol: c.symbol_b, t: Float64Array.from(c.dates, dayToEpoch), c: Float64Array.from(c.b) },
    };
  }, [d]);

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">TRA</span> TOTAL RETURN · {symbols.join(", ")} VS {vs} · {range}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · J/K MOVE · R RANGE · E CSV · F5 REFRESH</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="TRA SYM[,SYM...] [1M..MAX] [VS BENCHMARK]" />
      {d && (
        <div className="dim">
          TOTAL = PRICE CHANGE + DIVIDENDS (ADJUSTED CLOSES) · ANNUAL = COMPOUND RATE OVER THE DAYS SHOWN · EXCESS = ROW MINUS {d.benchmark.symbol} OVER THE
          ROW'S OWN DATES · PAST RETURNS, NOT A FORECAST
        </div>
      )}
      {d?.warnings.map((w) => (
        <div key={w} className="warn">
          {w}
        </div>
      ))}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
      {bars && d?.chart && (
        <div className="vis">
          <div className="dim">
            {d.chart.symbol_a} ({d.chart.basis_a}) VS {d.chart.symbol_b} ({d.chart.basis_b}) · BOTH REBASED TO 100 ON THE FIRST SHARED DATE
            {d.chart.basis_a !== d.chart.basis_b && <span className="warn"> · LINES ARE ON DIFFERENT BASES (TOTAL VS PRICE)</span>}
            {" · "}
            {num(d.chart.a[d.chart.a.length - 1], 1)} VS {num(d.chart.b[d.chart.b.length - 1], 1)} AT THE END
          </div>
          <ChartView
            key={`${key}:${env?.as_of}`}
            ref={chart}
            data={bars.main}
            compare={bars.other}
            type="LINE"
            log={false}
            readoutLabel={d.chart.symbol_a}
          />
        </div>
      )}
    </div>
  );
}
