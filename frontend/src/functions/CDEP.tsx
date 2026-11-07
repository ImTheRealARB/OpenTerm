/**
 * CDEP: spot order book depth. Binance first, OKX when Binance fails (HTTP 451 where Binance blocks the country); the header names the venue.
 * Bids and asks side by side with cumulative size and notional, spread, whole-book imbalance and notional within 0.1 / 0.5 / 1 % of mid.
 * Refreshes every 5 s. Keys: arrows move, E CSV, F5 refresh. `CDEP ETHUSDT 50` shows 50 levels.
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig, fmtNum, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { worldApi } from "../net/worldApi";
import { depthBar, ladder, parseCdepArgs, sPct, signClass, utc, type LadderRow } from "./cryptoArgs";
import { useEnvelope } from "./useEnvelope";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

export default function CDEP({ panelId, args }: FunctionProps) {
  const a = useMemo(() => parseCdepArgs(args), [args]);
  const { env, error, loading, reload: load } = useEnvelope(a.pair, (fresh) => worldApi.cdep(a.pair, fresh), 5_000);
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const rows = useMemo(() => (d ? ladder(d.bids, d.asks, a.levels) : []), [d, a.levels]);
  const max = useMemo(() => {
    const last = rows[rows.length - 1];
    return Math.max(last?.bid?.[3] ?? 0, last?.ask?.[3] ?? 0);
  }, [rows]);
  const latest = useLatest({ rows });

  const columns = useMemo<Column<LadderRow>[]>(
    () => [
      { title: "", width: 10, align: "right", text: (r) => depthBar(r.bid?.[3], max), color: () => "up" },
      { title: "CUM NOTNL", width: 10, align: "right", text: (r) => (r.bid ? fmtBig(r.bid[3]) : ""), color: () => "dim" },
      { title: "CUM QTY", width: 10, align: "right", text: (r) => (r.bid ? fmtNum(r.bid[2], 4) : "") },
      { title: "BID QTY", width: 10, align: "right", text: (r) => (r.bid ? fmtNum(r.bid[1], 4) : "") },
      { title: "BID", width: 11, align: "right", text: (r) => (r.bid ? fmtPrice(r.bid[0]) : ""), color: () => "up" },
      { title: "ASK", width: 11, align: "right", text: (r) => (r.ask ? fmtPrice(r.ask[0]) : ""), color: () => "down" },
      { title: "ASK QTY", width: 10, align: "right", text: (r) => (r.ask ? fmtNum(r.ask[1], 4) : "") },
      { title: "CUM QTY", width: 10, align: "right", text: (r) => (r.ask ? fmtNum(r.ask[2], 4) : "") },
      { title: "CUM NOTNL", width: 10, align: "right", text: (r) => (r.ask ? fmtBig(r.ask[3]) : ""), color: () => "dim" },
      { title: "", width: 10, text: (r) => depthBar(r.ask?.[3], max), color: () => "down" },
    ],
    [max],
  );
  useCsvExport(panelId, () => (d ? gridCsv(`CDEP_${d.symbol}`, columns.filter((c) => c.title), rows) : null));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (navKey(e, grid.current, latest.current.rows.length)) return true;
        return false;
      }),
    [panelId, latest],
  );

  const q = d?.usd ? "$" : d ? ` ${d.quote}` : "";
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">CDEP</span> ORDER BOOK · {d ? `${d.symbol} · ${d.venue}` : a.pair}
        {d?.ts_ms ? <span className="dim"> · BOOK {utc(d.ts_ms)} UTC</span> : null}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · 5S REFRESH · E CSV · F5</span>
      </div>
      {d && (
        <div className="line" data-testid="cdep-summary">
          MID <span className="acc">{fmtPrice(d.mid)}</span> · SPREAD {fmtPrice(d.spread)} ({d.spread_pct.toFixed(4)}%) · IMBALANCE{" "}
          <span className={signClass(d.imbalance_pct)}>{sPct(d.imbalance_pct, 1)}</span>
          <span className="dim"> (BIDS {fmtNum(d.bid_qty, 3)} VS ASKS {fmtNum(d.ask_qty, 3)} {d.base}, {d.levels[0]}/{d.levels[1]} LEVELS)</span>
        </div>
      )}
      {d && (
        <div className="line">
          {d.bands.map((b) => (
            <span key={b.pct}>
              ±{b.pct}%: BID {q === "$" ? "$" : ""}{fmtBig(b.bid)}{q !== "$" ? q : ""} / ASK {q === "$" ? "$" : ""}{fmtBig(b.ask)}{q !== "$" ? q : ""}{" "}
              <span className={signClass(b.imbalance_pct)}>{sPct(b.imbalance_pct, 1)}</span>
              {"   "}
            </span>
          ))}
        </div>
      )}
      {d && <div className="dim">IMBALANCE = (BID SIZE - ASK SIZE) / TOTAL, OVER THE LEVELS THE VENUE RETURNED (UP TO 100 A SIDE), NOT THE WHOLE BOOK.</div>}
      <ErrorLine error={error} hasData={!!d} usage="CDEP BTCUSDT [LEVELS]" />
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
