/**
 * LIQ: the latest filled liquidation orders of a USDT perpetual on OKX (`LIQ`, `LIQ ETH`). OKX returns only the most recent ~100 orders, so
 * the totals cover the span shown, not a fixed window; Binance publishes no liquidation history over REST. LONG = a long position was liquidated.
 * Keys: arrows move, E CSV, F5 refresh (auto every 20 s).
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig, fmtNum, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { worldApi, type LiqEvent } from "../net/api";
import { joinArg, span, utc } from "./cryptoArgs";
import { useEnvLoad } from "./cryptoLoad";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const side = (r: LiqEvent) => (r.side === "LONG" ? "down" : "up");
const COLUMNS: Column<LiqEvent>[] = [
  { title: "TIME (UTC)", width: 20, text: (r) => utc(r.t), color: () => "dim" },
  { title: "LIQUIDATED", width: 10, text: (r) => r.side, color: side },
  { title: "PRICE", width: 11, align: "right", text: (r) => fmtPrice(r.px) },
  { title: "SIZE", width: 10, align: "right", text: (r) => fmtNum(r.base, 4) },
  { title: "USD", width: 10, align: "right", text: (r) => "$" + fmtBig(r.usd), color: side },
  { title: "CONTRACT", width: 15, text: (r) => r.inst, color: () => "dim" },
];

export default function LIQ({ panelId, args }: FunctionProps) {
  const sym = useMemo(() => joinArg(args).toUpperCase() || "BTC", [args]);
  const { env, error, loading, load } = useEnvLoad((fresh) => worldApi.liq(sym, fresh), sym, 20_000);
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const rows = useMemo(() => d?.recent ?? [], [d]);
  const latest = useLatest({ rows });
  useCsvExport(panelId, () => (d ? gridCsv(`LIQ_${sym}`, COLUMNS, rows) : null));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        if (navKey(e, grid.current, latest.current.rows.length)) return true;
        if (e.key === "F5") {
          void load(true);
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">LIQ</span> LIQUIDATIONS · {d ? `${d.base}-USDT PERPETUAL · ${d.venue}` : sym}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · E CSV · F5</span>
      </div>
      {d && (
        <div className="line" data-testid="liq-summary">
          {d.events} ORDERS OVER {span(d.span_s)} ({utc(d.since_ms)} TO {utc(d.until_ms)} UTC) · LONGS{" "}
          <span className="down">{d.long.n} ${fmtBig(d.long.usd)}</span> · SHORTS <span className="up">{d.short.n} ${fmtBig(d.short.usd)}</span>
          {d.largest && <span className="dim"> · LARGEST {d.largest.side} ${fmtBig(d.largest.usd)} AT {fmtPrice(d.largest.px)}</span>}
        </div>
      )}
      {d && <div className="dim">{d.note} SHOWING THE NEWEST {rows.length}.</div>}
      {d && d.events === 0 && <div className="warn">NO FILLED LIQUIDATION ORDERS RETURNED FOR {d.base}.</div>}
      <ErrorLine error={error} hasData={!!d} usage="LIQ [BTC]" />
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
