/**
 * TRADE: exports and imports between two countries by HS product, one row per year (UN Comtrade, free key UN_COMTRADE_KEY).
 * `TRADE USA CHN 85 8Y` = USA reports its trade with China in HS chapter 85 over the last 8 years. No partner = the world total.
 * Without a key the panel says `KEY REQUIRED: set UN_COMTRADE_KEY in APIKEYS` (Enter opens APIKEYS) and shows nothing else.
 * Numbers are each reporter's own filing in US dollars (not mirror data); a year the reporter has not filed is blank.
 * Keys: up/down move, E CSV, F5 refresh.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, worldApi, type Envelope, type TradePayload, type TradeRow } from "../net/api";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { fmtUsd, parseTradeArgs, signColor } from "./usArgs";

const COLUMNS: Column<TradeRow>[] = [
  { title: "YEAR", width: 6, text: (r) => String(r.year), color: () => "acc" },
  { title: "EXPORTS", width: 12, align: "right", text: (r) => fmtUsd(r.exports) },
  { title: "IMPORTS", width: 12, align: "right", text: (r) => fmtUsd(r.imports) },
  { title: "TOTAL", width: 12, align: "right", text: (r) => fmtUsd(r.total), color: () => "dim" },
  { title: "BALANCE", width: 12, align: "right", text: (r) => fmtUsd(r.balance), color: (r) => signColor(r.balance) },
];

export default function TRADE({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parseTradeArgs(args), [args]);
  // The effect depends on these plain values, not on `p`, so a new args array with the same words does not refetch.
  const { reporter, partner, hs, years, error: error0 } = p;
  const [env, setEnv] = useState<Envelope<TradePayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const grid = useRef<GridHandle>(null);

  const load = useCallback(
    (fresh: boolean) => {
      if (error0) return Promise.resolve();
      setLoading(true);
      return worldApi
        .trade(reporter, partner || "WLD", hs, years, fresh)
        .then((e) => {
          setEnv(e);
          setError(null);
        })
        .catch((e: ApiError) => {
          setError(e);
          setEnv(null); // a different question must not keep showing the previous answer
        })
        .finally(() => setLoading(false));
    },
    [reporter, partner, hs, years, error0],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest({ rows });
  useCsvExport(panelId, () => (d ? gridCsv(`TRADE_${d.reporter.iso}_${d.partner.iso}_${d.cmd}`, COLUMNS, rows) : null));

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

  if (p.error) {
    return (
      <div className="fn">
        <div className="line"><span className="acc">TRADE</span> · {p.error}</div>
        <div className="dim">EXAMPLES: TRADE USA CHN · TRADE IND WORLD 27 · TRADE DEU USA 8703 10Y. FREE KEY: UN_COMTRADE_KEY IN APIKEYS.</div>
      </div>
    );
  }
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">TRADE</span> {d ? `${d.reporter.name.toUpperCase()} WITH ${d.partner.name.toUpperCase()} · ${d.cmd === "TOTAL" ? "ALL PRODUCTS" : `HS ${d.cmd}`}` : `${p.reporter} ${p.partner || "WORLD"} ${p.hs}`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · E CSV · F5 REFRESH</span>
      </div>
      {d && (
        <div className="line">
          {d.rows.length} YEARS, {d.rows[d.rows.length - 1].year} TO {d.rows[0].year} · <span className="dim">{d.cmd_desc.toUpperCase()} · USD</span>
        </div>
      )}
      {d && <div className="dim">SOURCE: {d.source}. {d.note}</div>}
      <ErrorLine error={error} hasData={!!d} usage="TRADE USA CHN 85" />
      {!d && !error && loading && <div className="dim">LOADING…</div>}
      {d && <Grid ref={grid} columns={COLUMNS} rows={rows} />}
    </div>
  );
}
