/**
 * DOM (Phase 23): a READ-ONLY depth ladder. `DOM BTCUSDT [LEVELS]`: one price column, asks above the spread (red), bids
 * below (green), each level's size and a size bar. Same venues and refresh as CDEP (Binance, then OKX; every 5 s).
 * There is no order entry here and never will be (NO LIVE ORDERS). An Indian symbol (`DOM RELIANCE.NS`) shows Kite's best FIVE levels a side
 * (needs a Kite login; the first answer takes a few seconds while the server switches that one instrument to Kite's full mode).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtNum, fmtPrice } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { recorderApi } from "../net/recorderApi";
import type { RecordedInfo } from "../net/recorderTypes";
import type { CdepPayload, Envelope } from "../net/types";
import { worldApi } from "../net/worldApi";
import { useLatest } from "../state/useLatest";
import { depthBar, parseCdepArgs, utc } from "./cryptoArgs";
import { domRows, type DomRow } from "./domMath";
import { usePanelRefresh } from "./panelRefresh";
import { stepIndex } from "./recArgs";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { RecordedLine } from "./RecordedLine";
import type { FunctionProps } from "./registry";
import { useEnvelope } from "./useEnvelope";

export default function DOM({ panelId, args }: FunctionProps) {
  const a = useMemo(() => parseCdepArgs(args), [args]);
  const levels = Math.min(a.levels, 50);
  // `REC=<id>`: a recorded session instead of the live book. It shows one snapshot at a time (`,` = older, `.` = newer);
  // it opens on the newest. `snap` is the 0-based index, -1 until the first answer says how many snapshots there are.
  const [snap, setSnap] = useState(-1);
  const load = (fresh: boolean): Promise<Envelope<CdepPayload & { recorded?: RecordedInfo }>> =>
    a.rec ? recorderApi.depth(a.rec, snap) : worldApi.cdep(a.pair, fresh);
  const { env, error, loading, reload } = useEnvelope(a.rec ? `${a.rec}#${snap}` : a.pair, load, a.rec ? 0 : 5_000);
  // A different recording (a new command in this panel) opens on its newest book again.
  useEffect(() => {
    setSnap(-1);
  }, [a.rec]);
  const d = env?.data;
  const rows = useMemo(() => (d ? domRows(d.bids, d.asks, levels) : []), [d, levels]);
  // Kite quantities are whole shares / lots; crypto sizes are fractions of a coin.
  const qtyDp = d?.venue.startsWith("KITE") ? 0 : 4;
  const max = useMemo(() => rows.reduce((m, r) => Math.max(m, r.qty), 0), [rows]);
  const grid = useRef<GridHandle>(null);
  const latest = useLatest({ rows, snap, count: d?.recorded?.count ?? 0, rec: !!a.rec });

  const columns = useMemo<Column<DomRow>[]>(
    () => [
      { title: "BID SIZE", width: 12, align: "right", text: (r) => (r.side === "bid" ? fmtNum(r.qty, qtyDp) : ""), color: () => "up" },
      { title: "", width: 10, align: "right", text: (r) => (r.side === "bid" ? depthBar(r.qty, max) : ""), color: () => "up" },
      { title: "PRICE", width: 12, align: "right", text: (r) => fmtPrice(r.price), color: (r) => (r.side === "ask" ? "down" : "up") },
      { title: "", width: 10, text: (r) => (r.side === "ask" ? depthBar(r.qty, max) : ""), color: () => "down" },
      { title: "ASK SIZE", width: 12, align: "right", text: (r) => (r.side === "ask" ? fmtNum(r.qty, qtyDp) : ""), color: () => "down" },
    ],
    [max, qtyDp],
  );

  // Start with the cursor on the best bid (just under the spread), where the eye goes first.
  const bestBid = rows.findIndex((r) => r.side === "bid");
  useEffect(() => {
    if (bestBid > 0) grid.current?.moveTo(bestBid);
  }, [bestBid, d?.symbol]);

  usePanelRefresh(panelId, () => void reload(true));
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { rec, snap: at, count } = latest.current;
        if (rec && count > 0 && (e.key === "," || e.key === ".")) {
          // The first answer for index -1 is the newest one (index count-1); stepping starts from the real index.
          const now = at < 0 ? count - 1 : at;
          setSnap(stepIndex(now, e.key === "," ? -1 : 1, count));
          return true;
        }
        return navKey(e, grid.current, latest.current.rows.length);
      }),
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">DOM</span> DEPTH LADDER (READ ONLY) · {d ? `${d.symbol} · ${d.venue}` : a.pair}
        {d?.ts_ms ? <span className="dim"> · BOOK {utc(d.ts_ms)} UTC</span> : null}
        {d?.recorded ? loading && <span className="dim"> · LOADING…</span> : <EnvStatus env={env} loading={loading} />}
        <span className="dim"> · {d?.venue.startsWith("KITE") ? "BEST 5" : levels} LEVELS A SIDE · {a.rec ? ", . = OLDER / NEWER BOOK" : "5S REFRESH"} · F5</span>
      </div>
      {d?.recorded && (
        <RecordedLine
          rec={d.recorded}
          extra={d.recorded.at && d.recorded.count ? `BOOK ${(d.recorded.index ?? 0) + 1} OF ${d.recorded.count}, SEEN ${utc(d.recorded.at)} UTC` : undefined}
        />
      )}
      {a.recError && <div className="line err">{a.recError}</div>}
      {d && (
        <div className="line" data-testid="dom-summary">
          MID <span className="acc">{fmtPrice(d.mid)}</span> · SPREAD {fmtPrice(d.spread)} ({d.spread_pct.toFixed(4)}%)
        </div>
      )}
      <ErrorLine error={error} hasData={!!d} usage="DOM BTCUSDT [LEVELS 5-50]" />
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
