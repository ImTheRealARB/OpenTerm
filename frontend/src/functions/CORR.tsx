/**
 * Correlation matrix of daily log returns over common trading dates (math: corr.ts).
 * A small DOM table (at most 20 x 20) so cells can carry heat classes; the grid canvas has no per-cell fills.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api9, type BarsAdj, type Envelope } from "../net/api";
import { navigate } from "../state/workspace";
import { correlationMatrix, corrBand, parseCorrArgs, type CloseSeries } from "./corrMath";
import { useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { useCsvExport } from "./tableExport";

interface Loaded {
  series: CloseSeries[];
  /** Per-symbol failure text, e.g. "FOO: NO DATA FOR FOO". */
  failed: string[];
  envs: Envelope<BarsAdj>[];
}

const fmtR = (r: number) => (Number.isFinite(r) ? r.toFixed(2) : "n/a");

export default function CORR({ panelId, args }: FunctionProps) {
  const { symbols, range, error: usage } = useMemo(() => parseCorrArgs(args), [args]);
  const [data, setData] = useState<Loaded | null>(null);
  const [loading, setLoading] = useState(false);
  const [cur, setCur] = useState({ r: 0, c: 0 });
  const curRef = useLatest(cur);

  const load = useCallback(
    (fresh: boolean) => {
      if (usage) return Promise.resolve();
      setLoading(true);
      return Promise.allSettled(symbols.map((s) => api9.history(s, range, "1d", fresh))).then((res) => {
        const series: CloseSeries[] = [];
        const failed: string[] = [];
        const envs: Envelope<BarsAdj>[] = [];
        res.forEach((x, i) => {
          if (x.status === "fulfilled") {
            const b = x.value.data;
            series.push({ symbol: symbols[i], t: b.t, c: b.adj && b.adj.length === b.t.length ? b.adj : b.c, tz: b.tz });
            envs.push(x.value);
          } else {
            const e = x.reason as ApiError;
            failed.push(`${symbols[i]}: ${e.message}${e.detail ? ` (${e.detail})` : ""}`);
          }
        });
        setData({ series, failed, envs });
        setLoading(false);
      });
    },
    [symbols, range, usage],
  );

  useEffect(() => {
    setData(null);
    void load(false);
  }, [load]);

  const result = useMemo(() => (data && data.series.length >= 2 ? correlationMatrix(data.series) : null), [data]);
  const syms = result?.symbols ?? [];
  const symsRef = useLatest(syms);

  useCsvExport(panelId, () =>
    result
      ? {
          name: `CORR_${range}_${syms.join("_")}`,
          header: ["", ...syms],
          rows: result.matrix.map((row, i) => [syms[i], ...row.map((v) => (Number.isFinite(v) ? Number(v.toFixed(4)) : ""))]),
        }
      : null,
  );

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const n = symsRef.current.length;
        if (!n) return e.key === "F5" ? (void load(true), true) : false;
        const move = (dr: number, dc: number) =>
          setCur((p) => ({ r: Math.max(0, Math.min(n - 1, p.r + dr)), c: Math.max(0, Math.min(n - 1, p.c + dc)) }));
        switch (e.key) {
          case "j":
          case "ArrowDown": move(1, 0); return true;
          case "k":
          case "ArrowUp": move(-1, 0); return true;
          case "h":
          case "ArrowLeft": move(0, -1); return true;
          case "l":
          case "ArrowRight": move(0, 1); return true;
          case "g":
          case "Home": setCur({ r: 0, c: 0 }); return true;
          case "G":
          case "End": setCur({ r: n - 1, c: n - 1 }); return true;
          case "Enter": {
            const { r, c } = curRef.current;
            const a = symsRef.current[r];
            const b = symsRef.current[c];
            if (a) navigate(panelId, { fn: "GP", security: { symbol: a }, args: b && b !== a ? [range, "VS", b] : [range] });
            return true;
          }
          case "F5":
            void load(true);
            return true;
        }
        return false;
      }),
    [panelId, load, range, symsRef, curRef],
  );

  const sel = result && cur.r < syms.length && cur.c < syms.length ? cur : { r: 0, c: 0 };
  const stale = data?.envs.some((x) => x.stale) ?? false;
  const age = data?.envs.length ? Math.max(...data.envs.map((x) => x.age_s)) : null;
  const sources = [...new Set((data?.envs ?? []).map((x) => (x.source ?? "").toUpperCase()))].join(",");
  const mixed = new Set((data?.series ?? []).map((s) => s.tz ?? "")).size > 1;
  const adjAll = data?.envs.length ? data.envs.every((x) => x.data.adj && x.data.adj.length === x.data.t.length) : false;

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">CORR</span> · {range} DAILY LOG RETURNS
        {result && ` · ${result.returns} RETURNS ${result.first}..${result.last} · ${sources}`}
        {result && <span className="dim"> · {adjAll ? "ADJUSTED CLOSES" : "RAW CLOSES (NO ADJ FROM SOME SOURCE)"}</span>}
        {age != null && <span className={stale ? "warn" : "dim"}> · {stale ? "STALE " : "AGE "}{fmtAge(age)}</span>}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim"> · H/J/K/L MOVE · ENTER CHART PAIR · E CSV · F5 REFRESH</span>
      </div>
      {usage && <div className="err">{usage}</div>}
      {data?.failed.map((f) => (
        <div className="err" key={f}>{f}</div>
      ))}
      {data && data.series.length < 2 && !usage && <div className="err">NEED AT LEAST 2 SYMBOLS WITH DATA</div>}
      {mixed && result && <div className="warn">MIXED EXCHANGE TIME ZONES: ONLY DATES TRADED ON EVERY EXCHANGE COUNT</div>}
      {result && result.returns < 20 && <div className="warn">ONLY {result.returns} COMMON RETURNS: THIN SAMPLE</div>}
      {result && (
        <div className="corr">
          <table className="t corr-t">
            <thead>
              <tr>
                <th />
                {syms.map((s) => (
                  <th key={s} className="n">{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.matrix.map((row, i) => (
                <tr key={syms[i]} className={i === sel.r ? "on" : ""}>
                  <th className="acc">{syms[i]}</th>
                  {row.map((v, j) => (
                    <td key={syms[j]} className={`n h-${corrBand(v) || "na"}${i === sel.r && j === sel.c ? " cur" : ""}`}>
                      {fmtR(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="sr" role="status" aria-live="polite">
            {syms[sel.r]} / {syms[sel.c]} {fmtR(result.matrix[sel.r][sel.c])}
          </div>
        </div>
      )}
    </div>
  );
}
