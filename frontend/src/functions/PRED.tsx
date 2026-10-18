/**
 * PRED: prediction markets from Polymarket and Kalshi (public, keyless, read only). Rows: question, YES price as a probability, volume, close date, source.
 * `PRED <text>` filters by question words, `SRC=POLY|KALSHI` keeps one source. Enter opens the outcome table and, where the source gives one, a price
 * history chart under the grid (Esc closes it). Every view says MARKET-IMPLIED PROBABILITY, NOT A FORECAST; one source down is named, never hidden.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartView, type BarData } from "../chart/ChartView";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, worldApi, type Envelope, type PredDetail, type PredPayload, type PredRow } from "../net/api";
import { EnvStatus, ErrorLine } from "./macroUi";
import { filterSrc, fmtOutcome, fmtProb, fmtVolume, parsePredArgs, PRED_LABEL, PRED_USAGE, predBars, sourceTag } from "./predArgs";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const NO_INDICATORS: never[] = [];

interface Open {
  source: PredRow["source"];
  id: string;
}

export default function PRED({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parsePredArgs(args), [args]);
  const [env, setEnv] = useState<Envelope<PredPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(!p.error);
  const [open, setOpen] = useState<Open | null>(null);
  const [det, setDet] = useState<Envelope<PredDetail> | null>(null);
  const [detError, setDetError] = useState<ApiError | null>(null);
  const [detLoading, setDetLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const grid = useRef<GridHandle>(null);

  useEffect(() => {
    if (p.error) return;
    let alive = true;
    setLoading(true);
    setOpen(null);
    worldApi
      .pred(p.q, reload > 0)
      .then((e) => {
        if (!alive) return;
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => {
        if (!alive) return;
        setError(e);
        setEnv(null); // a failed refresh never leaves old rows looking current
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [p.q, p.error, reload]);

  useEffect(() => {
    if (!open) {
      setDet(null);
      setDetError(null);
      return;
    }
    let alive = true;
    setDetLoading(true);
    setDet(null);
    setDetError(null);
    worldApi
      .predDetail(open.source, open.id, reload > 0)
      .then((e) => alive && setDet(e))
      .catch((e: ApiError) => alive && setDetError(e))
      .finally(() => alive && setDetLoading(false));
    return () => {
      alive = false;
    };
  }, [open, reload]);

  const d = env?.data;
  const rows = useMemo(() => (d ? filterSrc(d.rows, p.src) : []), [d, p.src]);
  const latest = useLatest({ rows, open });
  const columns = useMemo<Column<PredRow>[]>(
    () => [
      { title: "QUESTION", width: 62, text: (r) => r.question, color: (r) => (r.source === "kalshi" ? "fg" : "acc") },
      { title: "YES %", width: 14, align: "right", text: fmtProb },
      { title: "VOLUME", width: 11, align: "right", text: (r) => fmtVolume(r.volume, r.vol_unit) },
      { title: "CLOSE", width: 11, text: (r) => r.close ?? "", color: () => "dim" },
      { title: "SOURCE", width: 10, text: (r) => sourceTag(r.source), color: () => "dim" },
    ],
    [],
  );
  useCsvExport(panelId, () => (d ? gridCsv(`PRED_${p.q.replace(/\W+/g, "_") || "ALL"}`, columns, rows) : null));

  const bars = useMemo(() => (det ? (predBars(det.data) as BarData | null) : null), [det]);
  const pick = useCallback((r: PredRow | undefined) => r && setOpen({ source: r.source, id: r.id }), []);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.rows.length)) return true;
        switch (e.key) {
          case "Enter":
            pick(cur.rows[g?.selected() ?? -1]);
            return true;
          case "Escape":
            if (!cur.open) return false;
            setOpen(null);
            return true;
          case "F5":
            setReload((n) => n + 1);
            return true;
        }
        return false;
      }),
    [panelId, latest, pick],
  );

  if (p.error) {
    return (
      <div className="fn">
        <div className="line"><span className="acc">PRED</span> · {p.error}</div>
        <div className="warn" data-testid="pred-label">{PRED_LABEL}</div>
        <div className="dim">USAGE: {PRED_USAGE}</div>
      </div>
    );
  }
  const dd = det?.data;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">PRED</span>{p.q ? ` ${p.q.toUpperCase()}` : ""}{p.src !== "all" ? ` · ${p.src.toUpperCase()} ONLY` : ""}
        {d && <span className="acc"> · {rows.length} MARKETS</span>}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · J/K MOVE · ENTER OUTCOMES + HISTORY · ESC CLOSE · E CSV · F5 REFRESH</span>
      </div>
      <div className="warn" data-testid="pred-label">{PRED_LABEL}. READ ONLY: NO TRADING.</div>
      {d && <div className="dim">{d.unit_note}. PRICE = LAST TRADE (KALSHI: BID/ASK MIDPOINT WHEN IT HAS NOT TRADED). TOP MARKETS BY VOLUME ONLY, NOT EVERY MARKET.</div>}
      {d?.notes.map((n) => <div key={n} className="err">{n}</div>)}
      <ErrorLine error={error} hasData={false} usage="PRED fed" />
      {d && !loading && rows.length === 0 && <div className="warn">NO OPEN MARKET MATCHES {p.q ? p.q.toUpperCase() : "THAT"}{p.src !== "all" ? ` ON ${p.src.toUpperCase()}` : ""}</div>}
      <Grid ref={grid} columns={columns} rows={rows} />
      {open && (
        <div className="vis" data-testid="pred-detail">
          <div className="line">
            <span className="acc">{open.source.toUpperCase()}</span> {dd ? dd.question.toUpperCase() : open.id}
            {detLoading && <span className="dim"> · LOADING…</span>}
            {det && <span className={det.stale ? "warn" : "dim"}> · {det.stale ? "STALE" : "AGE"} {Math.round(det.age_s)}S</span>}
            {dd && !dd.open && <span className="warn"> · NOT OPEN FOR TRADING</span>}
          </div>
          <div className="warn">{PRED_LABEL}</div>
          {detError && <div className="err">{detError.message}{detError.detail ? ` (${detError.detail})` : ""}</div>}
          {dd && (
            <>
              {dd.outcomes.map((o) => (
                <div key={o.name} className="line">{fmtOutcome(o)}</div>
              ))}
              <div className="dim">
                {dd.basis.toUpperCase()} · VOLUME {fmtVolume(dd.volume, dd.vol_unit)}{dd.close ? ` · CLOSES ${dd.close}` : ""}
                {dd.liquidity != null ? ` · LIQUIDITY $${Math.round(dd.liquidity)}` : ""}{dd.open_interest != null ? ` · OPEN INTEREST ${Math.round(dd.open_interest)} ct` : ""}
              </div>
              {dd.history_note && <div className="warn" data-testid="pred-history-note">{dd.history_note}</div>}
              {bars && (
                <div className="xychart">
                  <ChartView key={`${dd.source}:${dd.id}`} data={bars} type="LINE" log={false} indicators={NO_INDICATORS} readoutLabel={`${dd.history_outcome.toUpperCase()} %`} />
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
