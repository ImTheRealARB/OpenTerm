/** US Treasury par yield curve with 1D / 1W / 1M / 1Y changes in basis points, and the usual curve spreads. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import { macroApi } from "../net/macroApi";
import type { Envelope, YieldCurve } from "../net/types";
import { navigate } from "../state/workspace";
import { bpChange, curveShape, fmtBp, fredIdForTenor, nyToday, spreadBp, yieldBar } from "./macroArgs";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import RatesView from "./RatesView";
import { gridCsv, useCsvExport } from "./tableExport";

const POLL_MS = 120_000;
const HORIZONS = ["1D", "1W", "1M", "1Y"] as const;
const SPREADS: [string, string][] = [["2Y", "10Y"], ["3M", "10Y"], ["5Y", "30Y"]];
const BAR_W = 34;

interface Row {
  tenor: string;
  y: number | null;
  d: (number | null)[];
  max: number;
}

const COLUMNS: Column<Row>[] = [
  { title: "TENOR", width: 6, text: (r) => r.tenor, color: () => "acc" },
  { title: "YIELD %", width: 9, align: "right", text: (r) => (r.y == null ? "-" : r.y.toFixed(2)) },
  ...HORIZONS.map(
    (h, i): Column<Row> => ({
      title: `${h} BP`,
      width: 7,
      align: "right",
      text: (r) => fmtBp(r.d[i]),
      color: (r) => ((r.d[i] ?? 0) > 0 ? "up" : (r.d[i] ?? 0) < 0 ? "down" : "dim"),
    }),
  ),
  { title: "CURVE", width: BAR_W, text: (r) => yieldBar(r.y, r.max, BAR_W), color: () => "dim" },
];

function buildRows(c: YieldCurve): Row[] {
  const max = Math.max(0, ...c.yields.map((y) => y ?? 0));
  return c.tenors.map((tenor, i) => ({
    tenor,
    y: c.yields[i],
    d: HORIZONS.map((h) => bpChange(c.yields[i], c.compare[h]?.yields[i])),
    max,
  }));
}

/** Phase 14: with an argument (EUR GBP CAD JPY SPRD AUCT NS <ccy>) the table views; with none, the US Treasury panel below. */
export default function RATES(props: FunctionProps) {
  return props.args.length ? <RatesView {...props} /> : <RatesUS {...props} />;
}

function RatesUS({ panelId }: FunctionProps) {
  const [env, setEnv] = useState<Envelope<YieldCurve> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [hint, setHint] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return macroApi
      .rates(fresh)
      .then((e) => {
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => setError(e))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void load(false);
    const t = setInterval(() => void load(false), POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const curve = env?.data ?? null;
  const rows = useMemo(() => (curve ? buildRows(curve) : []), [curve]);
  const latest = useLatest(rows);
  useCsvExport(panelId, () => gridCsv("RATES", COLUMNS, rows));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        setHint(null);
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (!r) return true;
            const id = fredIdForTenor(r.tenor);
            if (id) navigate(panelId, { fn: "FRED", security: undefined, args: [id, "5Y"] });
            else setHint(`FRED HAS NO DAILY SERIES FOR THE ${r.tenor} TENOR`);
            return true;
          }
        }
        return false;
      }),
    [panelId, latest],
  );

  const today = nyToday();
  const daysOld = curve ? Math.round((Date.parse(`${today}T00:00:00Z`) - Date.parse(`${curve.date}T00:00:00Z`)) / 86_400_000) : 0;
  const shape = curveShape(curve ? spreadBp(curve.tenors, curve.yields, "2Y", "10Y") : null);
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">US TREASURY PAR YIELD CURVE</span>
        {curve && ` · ${curve.date}`}
        {daysOld > 4 && <span className="warn"> ({daysOld} DAYS OLD)</span>}
        <EnvStatus env={env} loading={loading} />
        <span className="dim legend"> · J/K MOVE · ENTER PLOT HISTORY · E CSV · F5 REFRESH</span>
      </div>
      {curve && (
        <>
          {SPREADS.map(([a, b]) => {
            const now = spreadBp(curve.tenors, curve.yields, a, b);
            if (now == null) return null;
            return (
              <div className="line" key={a + b}>
                {a}{b} <span className={now < 0 ? "down" : "up"}>{fmtBp(now)} BP</span>
                {a === "2Y" && b === "10Y" && shape && <span className={shape === "INVERTED" ? "down" : "dim"}> {shape}</span>}
                <span className="dim">
                  {HORIZONS.map((h) => {
                    const c = curve.compare[h];
                    const then = c ? spreadBp(curve.tenors, c.yields, a, b) : null;
                    return ` · ${h} ${fmtBp(then == null ? null : now - then)}`;
                  })}
                </span>
              </div>
            );
          })}
          {curve.note && <div className="warn">{curve.note.toUpperCase()}</div>}
          {env?.fallback_from.includes("treasury") && (
            <div className="warn">TREASURY.GOV DID NOT ANSWER: FRED CONSTANT-MATURITY SERIES SHOWN (SAME PAR YIELDS, FEWER TENORS).</div>
          )}
        </>
      )}
      {hint && <div className="warn">{hint}</div>}
      <ErrorLine error={error} hasData={!!env} />
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
