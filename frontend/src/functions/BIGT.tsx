/**
 * BIGT: big trades. The largest recent Binance spot trades (a coin size `MIN=5` or a dollar size `USD=250K`), newest first, with the
 * aggressor side. Looks at up to the newest 5,000 trades: the header says how many and how many seconds that covers, so a quiet
 * answer is never mistaken for a quiet market. Default filter on a USD pair: USD=100K. Polls every 5 s.
 * `BIGT ETHUSDT MIN=50`, `BTCUSDT BIGT USD=500K`. Keys: arrows move, E CSV, F5 refresh.
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtNum, fmtPrice } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { flowApi } from "../net/flowApi";
import type { FlowTrade } from "../net/flowTypes";
import { useLatest } from "../state/useLatest";
import { clockMs, filterText, fmtQty, parseBigtArgs } from "./flowArgs";
import { usePanelRefresh } from "./panelRefresh";
import { EnvStatus, ErrorLine } from "./panelStatus";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { useEnvelope } from "./useEnvelope";

const POLL_MS = 5_000;

export default function BIGT({ panelId, args, security }: FunctionProps) {
  const a = useMemo(() => parseBigtArgs(args, security?.symbol), [args, security?.symbol]);
  const key = `${a.sym}|${a.min ?? ""}|${a.usd ?? ""}`;
  const { env, error, loading, reload } = useEnvelope(key, (fresh) => flowApi.bigtrades(a.sym, { min: a.min, usd: a.usd }, fresh), POLL_MS);
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest({ rows });

  const columns = useMemo<Column<FlowTrade>[]>(
    () => [
      { title: "TIME UTC", width: 13, text: (r) => clockMs(r.t), color: () => "dim" },
      { title: "SIDE", width: 5, text: (r) => r.side, color: (r) => (r.side === "BUY" ? "up" : "down") },
      { title: "PRICE", width: 13, align: "right", text: (r) => fmtPrice(r.p), color: (r) => (r.side === "BUY" ? "up" : "down") },
      { title: d ? `QTY ${d.base}` : "QTY", width: 12, align: "right", text: (r) => fmtQty(r.q) },
      { title: d ? (d.quote_is_usd ? "VALUE USD" : `VALUE ${d.quote}`) : "VALUE", width: 14, align: "right", text: (r) => fmtNum(r.value, 0) },
    ],
    [d],
  );
  useCsvExport(panelId, () => (d ? gridCsv(`BIGT_${d.symbol}`, columns, rows) : null));
  usePanelRefresh(panelId, () => {
    void reload(true);
  });
  useEffect(() => registerPanelKeys(panelId, (e) => navKey(e, grid.current, latest.current.rows.length)), [panelId, latest]);

  const buyValue = rows.filter((r) => r.side === "BUY").reduce((s, r) => s + r.value, 0);
  const sellValue = rows.filter((r) => r.side === "SELL").reduce((s, r) => s + r.value, 0);
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">BIGT</span> BIG TRADES · {d ? `${d.pair} · ${d.venue}` : a.sym}
        {d && <span className="dim"> · {d.basis}</span>}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · 5S REFRESH · E CSV · F5</span>
      </div>
      {a.error && <div className="err">{a.error}</div>}
      {d && (
        <div className="line" data-testid="bigt-summary">
          {filterText(d.filter, d.base)}: <span className="acc">{d.found}</span> OF {d.scanned} TRADES
          <span className="dim"> (THE NEWEST {d.scanned} TRADES COVER {d.span_s.toFixed(0)}S{d.found > rows.length ? `, SHOWING ${rows.length}` : ""}) · </span>
          <span className="up">BUY {fmtNum(buyValue, 0)}</span> / <span className="down">SELL {fmtNum(sellValue, 0)}</span>
          <span className="dim"> {d.quote_is_usd ? "USD" : d.quote}</span>
        </div>
      )}
      {d && d.found === 0 && <div className="dim">NO TRADE THAT BIG IN THIS WINDOW. LOWER THE FILTER (MIN=0.5, USD=25K) OR WAIT; THE WINDOW IS THE LATEST {d.span_s.toFixed(0)}S.</div>}
      <ErrorLine error={error} hasData={!!d} usage="BIGT BTCUSDT [MIN=COINS|USD=AMOUNT]" />
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
