/**
 * SEAS: seasonality of one security from its full daily history (math: seasMath.ts).
 * A small DOM table with a bar column; `V` cycles MONTH / WEEKDAY / DOM / WOY.
 */
import { useEffect, useMemo, useState } from "react";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";
import type { BarsAdj, Envelope } from "../net/types";
import { replaceView } from "../state/workspace";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { parseSeasArgs, SEAS_KINDS, seasonality, type SeasKind } from "./seasMath";
import { useCsvExport } from "./tableExport";

const pct = (v: number, d = 2) => (Number.isFinite(v) ? `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%` : "n/a");
const BAR = 20;

function bar(v: number, scale: number): string {
  if (!Number.isFinite(v) || scale <= 0) return "";
  const n = Math.min(BAR, Math.round((Math.abs(v) / scale) * BAR));
  return "█".repeat(n);
}

export default function SEAS({ panelId, security, args }: FunctionProps) {
  const symbol = security!.symbol;
  const { kind } = useMemo(() => parseSeasArgs(args), [args]);
  const [env, setEnv] = useState<Envelope<BarsAdj> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cur, setCur] = useState(0);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    setEnv(null);
    setError(null);
    marketApi
      .history(symbol, "MAX", "1d", reload > 0)
      .then((e) => {
        if (!live) return;
        // The backend labels bars with the size the source really sent; monthly bars would give fake "daily" returns.
        if (e.data.interval && e.data.interval !== "1d") setError(`SOURCE SENT ${e.data.interval} BARS, SEAS NEEDS DAILY BARS (${e.source})`);
        else setEnv(e);
      })
      .catch((e: ApiError) => live && setError(`${e.message}${e.detail ? ` (${e.detail})` : ""}`));
    return () => {
      live = false;
    };
  }, [symbol, reload]);

  const result = useMemo(() => {
    if (!env) return null;
    const b = env.data;
    const t = Float64Array.from(b.t);
    const use = b.adj && b.adj.length === b.t.length ? b.adj : b.c;
    const c = Float64Array.from(use, (x) => (x == null ? NaN : x));
    return seasonality(t, c, kind, { excludeOpenPeriodAt: Date.now() / 1000, tz: b.tz });
  }, [env, kind]);

  const rowsRef = useLatest(result?.rows ?? []);
  const kindRef = useLatest(kind);
  usePanelRefresh(panelId, () => { setReload((r) => r + 1); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const n = rowsRef.current.length;
        switch (e.key) {
          case "j":
          case "ArrowDown": setCur((c) => Math.min(Math.max(0, n - 1), c + 1)); return true;
          case "k":
          case "ArrowUp": setCur((c) => Math.max(0, c - 1)); return true;
          case "g":
          case "Home": setCur(0); return true;
          case "G":
          case "End": setCur(Math.max(0, n - 1)); return true;
          case "v":
          case "V": {
            const next = SEAS_KINDS[(SEAS_KINDS.indexOf(kindRef.current) + 1) % SEAS_KINDS.length];
            setCur(0);
            replaceView(panelId, (v) => ({ ...v, args: [next] }));
            return true;
          }
        }
        return false;
      }),
    [panelId, rowsRef, kindRef],
  );

  useCsvExport(panelId, () =>
    result
      ? {
          name: `SEAS_${symbol}_${kind}`,
          header: ["bucket", "n", "avg_pct", "median_pct", "hit_pct", "min_pct", "max_pct"],
          rows: result.rows.map((r) => [r.label, r.n, ...[r.avg, r.median, r.hit, r.min, r.max].map((v) => (Number.isFinite(v) ? Number((v * 100).toFixed(4)) : ""))]),
        }
      : null,
  );

  const rows = result?.rows ?? [];
  const sel = Math.min(cur, Math.max(0, rows.length - 1));
  const scale = Math.max(0, ...rows.map((r) => (Number.isFinite(r.avg) ? Math.abs(r.avg) : 0)));
  const src = (env?.source ?? "").toUpperCase();
  const what = kind === "MONTH" ? "MONTH RETURN" : kind === "WOY" ? "ISO WEEK RETURN" : "DAILY RETURN";
  const thin = result && result.obs > 0 && result.obs < 30;

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">SEAS</span> {symbol} · {kind} · {what}
        {result && ` · ${result.firstYear}..${result.lastYear} · ${result.bars} DAILY BARS · ${result.obs} OBS · ${src}`}
        {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
        {!env && !error && <span className="dim"> · LOADING…</span>}
        <span className="dim legend"> · V VIEW · J/K MOVE · E CSV · F5 REFRESH</span>
      </div>
      {error && <div className="err">{error}</div>}
      {env && <div className="dim">{env.data.adj && env.data.adj.length === env.data.t.length ? "ADJUSTED CLOSES" : "RAW CLOSES (NO ADJUSTED SERIES FROM THIS SOURCE)"} · PAST AVERAGES, NOT A FORECAST</div>}
      {thin && <div className="warn">ONLY {result!.obs} OBSERVATIONS: THIN SAMPLE</div>}
      {result && result.obs === 0 && <div className="err">NOT ENOUGH HISTORY FOR {kind}</div>}
      {result && result.obs > 0 && (
        <div className="corr">
          <table className="t">
            <colgroup>
              <col style={{ width: "6ch" }} />
              <col style={{ width: "5ch" }} />
              <col style={{ width: "9ch" }} />
              <col style={{ width: "9ch" }} />
              <col style={{ width: "7ch" }} />
              <col style={{ width: "9ch" }} />
              <col style={{ width: "9ch" }} />
              <col />
            </colgroup>
            <thead>
              <tr>
                <th>{kind}</th>
                <th className="n">N</th>
                <th className="n">AVG</th>
                <th className="n">MEDIAN</th>
                <th className="n">HIT</th>
                <th className="n">MIN</th>
                <th className="n">MAX</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.label} className={i === sel ? "on" : ""}>
                  <td className="acc">{r.label}</td>
                  <td className="n">{r.n}</td>
                  <td className={`n ${r.avg >= 0 ? "up" : "down"}`}>{pct(r.avg)}</td>
                  <td className="n">{pct(r.median)}</td>
                  <td className="n">{Number.isFinite(r.hit) ? `${Math.round(r.hit * 100)}%` : "n/a"}</td>
                  <td className="n down">{pct(r.min)}</td>
                  <td className="n up">{pct(r.max)}</td>
                  <td className={r.avg >= 0 ? "up" : "down"}>{bar(r.avg, scale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="sr" role="status" aria-live="polite">
            {rows[sel] ? `${rows[sel].label} N ${rows[sel].n} AVG ${pct(rows[sel].avg)} HIT ${Number.isFinite(rows[sel].hit) ? Math.round(rows[sel].hit * 100) : "n/a"}%` : ""}
          </div>
        </div>
      )}
    </div>
  );
}

export type { SeasKind };
