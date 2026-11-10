/** Historical price table: newest bar first, with change % and (when the source has it) adjusted close. */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtBig, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { marketApi } from "../net/marketApi";
import type { BarsAdj } from "../net/types";
import { navigate } from "../state/workspace";
import { dayKey } from "./corrMath";
import { fallbackText } from "./fallbackText";
import { dirColor } from "./quoteRows";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { histArgs, histRows, type HistRow } from "./returns";
import { useEnvelope } from "./secPanel";
import { gridCsv, useCsvExport } from "./tableExport";

const INTERVALS: Record<string, string> = { D: "1d", W: "1wk", MO: "1mo" };
const INTERVAL_LABEL: Record<string, string> = { D: "DAILY", W: "WEEKLY", MO: "MONTHLY" };

export default function HIST({ panelId, security, args, source }: FunctionProps) {
  const symbol = security!.symbol;
  const { range, interval, bad } = useMemo(() => histArgs(args), [args]);
  const grid = useRef<GridHandle>(null);

  // useEnvelope drops an answer for an old symbol/range that lands after a re-key.
  const { env, error, loading, reload: load } = useEnvelope<BarsAdj>(`${symbol}|${range}|${interval}|${source ?? ""}`, (fresh) =>
    marketApi.history(symbol, range, INTERVALS[interval], fresh, source),
  );

  const tz = env?.data.tz ?? null;
  const rows = useMemo(() => (env ? histRows(env.data) : []), [env]);
  const hasAdj = rows.some((r) => r.adj != null);
  const latest = useLatest(rows);

  const columns = useMemo<Column<HistRow>[]>(() => {
    const cols: Column<HistRow>[] = [
      { title: "DATE", width: 10, text: (r) => dayKey(r.t, tz), color: () => "acc" },
      { title: "OPEN", width: 11, align: "right", text: (r) => fmtPrice(r.open) },
      { title: "HIGH", width: 11, align: "right", text: (r) => fmtPrice(r.high) },
      { title: "LOW", width: 11, align: "right", text: (r) => fmtPrice(r.low) },
      { title: "CLOSE", width: 11, align: "right", text: (r) => fmtPrice(r.close) },
    ];
    if (hasAdj) cols.push({ title: "ADJ CLOSE", width: 11, align: "right", text: (r) => fmtPrice(r.adj), color: () => "dim" });
    cols.push(
      { title: "CHG%", width: 8, align: "right", text: (r) => fmtPct(r.changePct), color: (r) => dirColor(r.changePct) },
      { title: "VOLUME", width: 8, align: "right", text: (r) => fmtBig(r.volume) },
    );
    return cols;
  }, [tz, hasAdj]);

  useCsvExport(panelId, () => (rows.length ? gridCsv(`HIST_${symbol}_${range}_${interval}`, columns, rows) : null));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (navKey(e, grid.current, latest.current.length)) return true;
        switch (e.key) {
          case "Enter":
            navigate(panelId, { fn: "GP", security: { symbol }, args: [range, ...(interval === "D" ? [] : [interval])] });
            return true;
        }
        return false;
      }),
    [panelId, latest, symbol, range, interval],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">{symbol}</span> · HISTORY {range} {INTERVAL_LABEL[interval]}
        {env && ` · ${rows.length} BARS${env.data.currency ? ` · ${env.data.currency}` : ""} · ${(env.source ?? "").toUpperCase()}`}
        {env && !hasAdj && rows.length > 0 && <span className="dim"> · NO ADJ CLOSE FROM THIS SOURCE</span>}
        {env && env.fallback_from.length > 0 && <span className="warn"> · {fallbackText(env.fallback_from, env.fallback_notes)}</span>}
        {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim legend"> · J/K MOVE · ENTER CHART · E CSV · F5 REFRESH</span>
      </div>
      {bad.length > 0 && <div className="err">CANNOT READ {bad.join(" ")} · USAGE: HIST [1M|3M|6M|YTD|1Y|2Y|5Y|10Y|MAX] [D|W|MO]</div>}
      {error && (
        <div className="err">
          {error.message}
          {error.detail && <span className="dim"> ({error.detail})</span>}
        </div>
      )}
      {env && !rows.length && !error && <div className="warn">NO BARS RETURNED FOR {symbol} {range}</div>}
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
