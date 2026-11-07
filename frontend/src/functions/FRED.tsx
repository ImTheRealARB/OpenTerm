/** FRED series plot: any FRED series by id, drawn with the shared chart component (line / area, log scale). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartView, type BarData, type ChartHandle, type ChartType } from "../chart/ChartView";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import { macroApi } from "../net/macroApi";
import type { Envelope, FredSeries } from "../net/types";
import { navigate, replaceView } from "../state/workspace";
import { FRED_RANGES, fmtSeriesChange, fmtSeriesValue, parseFredArgs } from "./macroArgs";
import { EnvStatus, ErrorLine } from "./panelStatus";
import type { FunctionProps } from "./registry";
import { useCsvExport } from "./tableExport";

const INTERVAL: Record<string, string> = { Daily: "1d", Weekly: "1wk" };
const NO_INDICATORS: never[] = [];

/** Observations as chart bars (open = high = low = close). Missing observations are skipped, not interpolated. */
function toSeriesBars(s: FredSeries): BarData {
  const keep: number[] = [];
  for (let i = 0; i < s.v.length; i++) if (s.v[i] != null) keep.push(i);
  const c = Float64Array.from(keep, (i) => s.v[i] as number);
  const interval = INTERVAL[s.frequency?.split(",")[0] ?? ""] ?? (s.frequency ? "1mo" : "1d");
  return { symbol: s.id, interval, tz: "UTC", t: Float64Array.from(keep, (i) => s.t[i]), o: c, h: c, l: c, c, v: new Float64Array(keep.length) };
}

export default function FRED({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parseFredArgs(args), [args]);
  const [env, setEnv] = useState<Envelope<FredSeries> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [type, setType] = useState<ChartType>("LINE");
  const [log, setLog] = useState(false);
  const [crossOn, setCrossOn] = useState(false);
  const [reload, setReload] = useState(0);
  const chart = useRef<ChartHandle>(null);
  const pRef = useRef(p);
  pRef.current = p;

  useEffect(() => {
    if (!p.id) return;
    let alive = true;
    setLoading(true);
    macroApi
      .fred(p.id, p.range, reload > 0)
      .then((e) => {
        if (!alive) return;
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [p.id, p.range, reload]);

  // Data for another series or range is not shown under this one's title.
  const cur = env && env.data.id === p.id && env.data.range === p.range ? env : null;
  const bars = useMemo(() => (cur ? toSeriesBars(cur.data) : null), [cur]);

  // useCallback: it depends only on panelId (pRef is a ref), so the key handler below can list it without re-registering every render.
  const setRange = useCallback((range: string) => replaceView(panelId, (v) => ({ ...v, args: [pRef.current.id ?? "", range].filter(Boolean) })), [panelId]);
  const latest = useRef({ cur, crossOn });
  useCsvExport(panelId, () => cur && { name: `FRED_${cur.data.id}`, header: ["date", cur.data.id], rows: cur.data.t.map((t, i) => [new Date(t * 1000).toISOString().slice(0, 10), cur.data.v[i] == null ? "" : String(cur.data.v[i])]) });
  latest.current = { cur, crossOn };

  usePanelRefresh(panelId, () => { setReload((r) => r + 1); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const n = Number(e.key);
        if (n >= 1 && n <= FRED_RANGES.length) {
          setRange(FRED_RANGES[n - 1]);
          return true;
        }
        switch (e.key) {
          case "c":
            setType((t) => (t === "LINE" ? "AREA" : "LINE"));
            return true;
          case "l":
            setLog((x) => !x);
            return true;
          case "x": {
            const on = !latest.current.crossOn;
            chart.current?.crosshair(on);
            setCrossOn(on);
            return true;
          }
          case "ArrowLeft":
            if (latest.current.crossOn) chart.current?.crosshairStep(-1);
            else chart.current?.pan(-10);
            return true;
          case "ArrowRight":
            if (latest.current.crossOn) chart.current?.crosshairStep(1);
            else chart.current?.pan(10);
            return true;
          case "+":
          case "=":
            chart.current?.zoom(0.8);
            return true;
          case "-":
            chart.current?.zoom(1.25);
            return true;
          case "m":
            navigate(panelId, { fn: "MACRO", args: [], security: undefined });
            return true;
        }
        return false;
      }),
    [panelId, setRange],
  );

  if (!p.id) {
    return (
      <div className="fn">
        <div className="line">
          <span className="acc">FRED</span> · USAGE: FRED SERIES_ID [{FRED_RANGES.join("|")}] · E.G. FRED UNRATE, FRED DGS10 10Y
        </div>
        <div className="dim">MACRO LISTS COMMON SERIES (OR PRESS M). ANY SERIES ID FROM FRED.STLOUISFED.ORG WORKS.</div>
      </div>
    );
  }

  const d = cur?.data;
  return (
    <div className="fn" style={{ position: "relative" }}>
      <div className="line">
        <span className="acc">{p.id}</span>
        {d?.title && ` ${d.title.toUpperCase()}`} · {p.range}
        {d?.units && <span className="dim"> · {d.units.toUpperCase()}</span>}
        {d?.frequency && <span className="dim"> · {d.frequency.toUpperCase()}{d.seasonal_adjustment ? ` ${d.seasonal_adjustment.toUpperCase()}` : ""}</span>}
        <EnvStatus env={cur} loading={loading} />
        {crossOn && <span className="acc"> · CROSSHAIR (←/→, X TO EXIT)</span>}
      </div>
      {d && (
        <div className="line">
          LAST <span className="acc">{fmtSeriesValue(d.last_value)}</span> ({d.last_date})
          {d.change != null && (
            <span className={d.change > 0 ? "up" : d.change < 0 ? "down" : "dim"}> {fmtSeriesChange(d.change)} VS PRIOR OBS</span>
          )}
          {d.missing > 0 && <span className="warn"> · {d.missing} MISSING OBS SKIPPED</span>}
          {d.meta_source === "none" && <span className="dim"> · NO TITLE OR UNITS FROM THE KEYLESS SOURCE (FRED_API_KEY ADDS THEM)</span>}
          <span className="dim"> · 1-6 RANGE · C LINE/AREA · L LOG · ←/→ PAN · +/- ZOOM · X CROSS · M MACRO · E CSV · F5 · DATA: FRED, FEDERAL RESERVE BANK OF ST. LOUIS</span>
        </div>
      )}
      {p.ignored.length > 0 && <div className="warn">IGNORED: {p.ignored.join(" ")}. ONE SERIES PER PANEL.</div>}
      <ErrorLine error={error} hasData={!!cur} usage="FRED SERIES_ID [1Y|2Y|5Y|10Y|20Y|MAX]" />
      {error?.kind === "not_found" && <div className="dim">TRY MACRO FOR A LIST OF COMMON SERIES.</div>}
      {!bars && !error && <div className="dim">LOADING {p.id} {p.range}…</div>}
      {bars && d && (
        <ChartView key={`${d.id}:${p.range}`} ref={chart} data={bars} type={type} log={log} indicators={NO_INDICATORS} readoutLabel={d.units ? d.units.split(" ").slice(0, 2).join(" ").toUpperCase() : d.id} />
      )}
    </div>
  );
}
