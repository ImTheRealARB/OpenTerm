/**
 * ECST: one country-level indicator as a line chart. World Bank API v2 first, DBnomics (IMF WEO mirror) second; `ECST DBN:<provider>/<dataset>/<series>` plots any DBnomics series.
 * Annual values sit on the last day of their year. The header names the source, the last data period and the provider's update date.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ChartView, type BarData, type ChartHandle, type ChartType } from "../chart/ChartView";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import type { Envelope, WorldSeries } from "../net/types";
import { worldApi } from "../net/worldApi";
import { EnvStatus, ErrorLine } from "./macroUi";
import type { FunctionProps } from "./registry";
import { useCsvExport } from "./tableExport";
import { fmtStat, parseEcstArgs } from "./worldArgs";

const NO_INDICATORS: never[] = [];

function toBars(s: WorldSeries): BarData {
  const c = Float64Array.from(s.v);
  const interval = s.freq === "ANNUAL" ? "1mo" : s.freq.startsWith("M") ? "1mo" : "1d";
  return { symbol: `${s.country}.${s.indicator}`, interval, tz: "UTC", t: Float64Array.from(s.t), o: c, h: c, l: c, c, v: new Float64Array(c.length) };
}

export default function ECST({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parseEcstArgs(args), [args]);
  const [env, setEnv] = useState<Envelope<WorldSeries> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [type, setType] = useState<ChartType>("LINE");
  const [crossOn, setCrossOn] = useState(false);
  const [reload, setReload] = useState(0);
  const chart = useRef<ChartHandle>(null);
  const crossRef = useRef(false);
  crossRef.current = crossOn;

  useEffect(() => {
    if (p.error) return;
    let alive = true;
    setLoading(true);
    setEnv(null);
    worldApi
      .stats(p.country, p.ind, reload > 0)
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
  }, [p.country, p.ind, p.error, reload]);

  const d = env?.data;
  const bars = useMemo(() => (d ? toBars(d) : null), [d]);
  useCsvExport(panelId, () => d ? { name: `ECST_${d.country}_${d.indicator}`, header: ["period", d.indicator], rows: d.periods.map((per, i) => [per, String(d.v[i])]) } : null);

  usePanelRefresh(panelId, () => { setReload((r) => r + 1); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        switch (e.key) {
          case "c":
            setType((t) => (t === "LINE" ? "AREA" : "LINE"));
            return true;
          case "x": {
            const on = !crossRef.current;
            chart.current?.crosshair(on);
            setCrossOn(on);
            return true;
          }
          case "ArrowLeft":
            if (crossRef.current) chart.current?.crosshairStep(-1);
            else chart.current?.pan(-3);
            return true;
          case "ArrowRight":
            if (crossRef.current) chart.current?.crosshairStep(1);
            else chart.current?.pan(3);
            return true;
          case "+":
          case "=":
            chart.current?.zoom(0.8);
            return true;
          case "-":
            chart.current?.zoom(1.25);
            return true;
        }
        return false;
      }),
    [panelId],
  );

  if (p.error) {
    return (
      <div className="fn">
        <div className="line"><span className="acc">ECST</span> · {p.error}</div>
        <div className="dim">EXAMPLES: ECST USA CPI · ECST GERMANY GDPG · ECST IN UNEMP · ECST BRA DEBT · ECST DBN:IMF/WEO:latest/USA.NGDP_RPCH</div>
        <div className="dim">INDICATORS: GDP GDPG GDPPC CPI UNEMP POP DEBT CA TRADE. SOURCES: WORLD BANK, THEN DBNOMICS (IMF WEO).</div>
      </div>
    );
  }
  return (
    <div className="fn" style={{ position: "relative" }}>
      <div className="line">
        <span className="acc">ECST</span> {d ? `${d.country_name.toUpperCase()} · ${d.label.toUpperCase()}` : `${p.country.toUpperCase()} ${p.ind.toUpperCase()}`}
        {d?.unit && <span className="dim"> · {d.unit.toUpperCase()}</span>}
        <EnvStatus env={env} loading={loading} />
        {crossOn && <span className="acc"> · CROSSHAIR (←/→, X TO EXIT)</span>}
      </div>
      {d && (
        <div className="line">
          LAST <span className="acc">{fmtStat(d.last_value, d.unit)}</span> ({d.last_period}) · {d.periods.length} OBS FROM {d.periods[0]} · {d.freq}
          <span className="dim"> · {d.source.toUpperCase()}{d.updated ? ` · SOURCE UPDATED ${d.updated.slice(0, 10)}` : ""}</span>
          {env && env.fallback_from.length > 0 && <span className="warn"> · FELL BACK FROM {env.fallback_from.join(", ").toUpperCase()}</span>}
          <span className="dim"> · C LINE/AREA · ←/→ PAN · +/- ZOOM · X CROSS · E CSV · F5</span>
        </div>
      )}
      <ErrorLine error={error} hasData={!!d} usage="ECST USA CPI" />
      {!bars && !error && <div className="dim">LOADING…</div>}
      {bars && d && <ChartView key={`${d.country}:${d.indicator}:${d.source}`} ref={chart} data={bars} type={type} log={false} indicators={NO_INDICATORS} readoutLabel={d.indicator} />}
    </div>
  );
}
