/**
 * TAS: time and sales. Every recent Binance spot trade, newest first, with the AGGRESSOR side the exchange reports
 * (BUY = bought at the ask, SELL = sold into the bid). Crypto only; any other symbol says ORDER FLOW: CRYPTO ONLY (BINANCE SPOT PAIRS).
 * Polls every 3 s while open (the server caches 2 s). Keys: arrows move, E CSV, F5 refresh. `TAS ETHUSDT` or `BTCUSDT TAS`.
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtNum, fmtPrice } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { flowApi } from "../net/flowApi";
import type { FlowTrade, TasPayload } from "../net/flowTypes";
import { recorderApi } from "../net/recorderApi";
import type { RecordedInfo } from "../net/recorderTypes";
import type { Envelope } from "../net/types";
import { useLatest } from "../state/useLatest";
import { clockMs, fmtQty, parseTasArgs } from "./flowArgs";
import { usePanelRefresh } from "./panelRefresh";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { RecordedLine } from "./RecordedLine";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { useEnvelope } from "./useEnvelope";

const ROWS = 200; // how many of the newest trades the panel asks for (the server allows 1,000)
const POLL_MS = 3_000;

export default function TAS({ panelId, args, security }: FunctionProps) {
  const a = useMemo(() => parseTasArgs(args, security?.symbol), [args, security?.symbol]);
  // `REC=<id>`: a recorded session instead of live trades. It never changes, so it is read once and not polled.
  const load = (fresh: boolean): Promise<Envelope<TasPayload & { recorded?: RecordedInfo }>> =>
    a.rec ? recorderApi.tas(a.rec, ROWS) : flowApi.trades(a.sym, ROWS, fresh);
  const { env, error, loading, reload } = useEnvelope(a.rec ?? a.sym, load, a.rec ? 0 : POLL_MS);
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest({ rows });

  // Side and price share the side's colour (green = aggressor bought, red = aggressor sold): that is the one thing worth scanning for.
  const columns = useMemo<Column<FlowTrade>[]>(
    () => [
      { title: "TIME UTC", width: 13, text: (r) => clockMs(r.t), color: () => "dim" },
      { title: "SIDE", width: 5, text: (r) => r.side, color: (r) => (r.side === "BUY" ? "up" : "down") },
      { title: "PRICE", width: 13, align: "right", text: (r) => fmtPrice(r.p), color: (r) => (r.side === "BUY" ? "up" : "down") },
      { title: d ? `QTY ${d.base}` : "QTY", width: 12, align: "right", text: (r) => fmtQty(r.q) },
      { title: d ? (d.quote_is_usd ? "VALUE USD" : `VALUE ${d.quote}`) : "VALUE", width: 13, align: "right", text: (r) => fmtNum(r.value, 2), color: () => "dim" },
    ],
    [d],
  );
  useCsvExport(panelId, () => (d ? gridCsv(`TAS_${d.symbol}`, columns, rows) : null));
  usePanelRefresh(panelId, () => {
    void reload(true);
  });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => navKey(e, grid.current, latest.current.rows.length)),
    [panelId, latest],
  );

  const buys = rows.filter((r) => r.side === "BUY").length;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">TAS</span> TIME AND SALES · {d ? `${d.pair} · ${d.venue}` : a.sym}
        {d && <span className="dim"> · {d.basis}</span>}
        {d?.recorded ? loading && <span className="dim"> · LOADING…</span> : <EnvStatus env={env} loading={loading} />}
        <span className="dim"> · {a.rec ? "" : "3S REFRESH · "}E CSV · F5</span>
      </div>
      {d?.recorded && <RecordedLine rec={d.recorded} />}
      {a.recError && <div className="line err">{a.recError}</div>}
      {d && (
        <div className="line" data-testid="tas-summary">
          LAST {rows.length} TRADES{" "}
          <span className="dim">
            ({d.n} HELD, {d.span_s.toFixed(0)}S) ·{" "}
          </span>
          <span className="up">{buys} BUY</span> / <span className="down">{rows.length - buys} SELL</span>
          <span className="dim"> · SIDE = <span data-term="AGGRESSOR">AGGRESSOR</span>: BUY HIT THE ASK, SELL HIT THE BID. NEWEST FIRST.</span>
        </div>
      )}
      <ErrorLine error={error} hasData={!!d} usage="TAS BTCUSDT" />
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
