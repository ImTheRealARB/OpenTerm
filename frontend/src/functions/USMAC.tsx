/**
 * USMAC: US macro series from three free, keyed, read-only sources.
 *   USMAC BLS [CPI UNEMP ...]          US Bureau of Labor Statistics: prices, jobs, wages, job openings (BLS_API_KEY)
 *   USMAC BEA [GDPG GDP TRADEBAL ...]  US Bureau of Economic Analysis: GDP, trade balance, value added by industry (BEA_API_KEY)
 *   USMAC CENSUS [RETAIL AUTO] | [TRADE CHINA 85]   US Census Bureau: retail sales, goods trade by country and HS chapter (CENSUS_API_KEY)
 * A board shows one row per series with its own latest period; Enter opens a series' history, Backspace goes back. One named series opens
 * on its history straight away. Without the key: `KEY REQUIRED: set X in APIKEYS`, no numbers. Keys: Enter, Backspace, E CSV, F5.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import type { Envelope, UsMacroPayload, UsSeries } from "../net/types";
import { worldApi } from "../net/worldApi";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { fmtChange, fmtNum, parseUsmacArgs, signColor } from "./usArgs";

interface PointRow {
  kind: UsSeries["kind"]; // decides how the change is written (pp for a rate, % for a level)
  period: string;
  value: number | null;
  chg: number | null;
  pct: number | null;
}

const BOARD: Column<UsSeries>[] = [
  { title: "SERIES", width: 9, text: (r) => r.alias, color: () => "acc" },
  { title: "NAME", width: 44, text: (r) => r.label },
  { title: "LAST", width: 14, align: "right", text: (r) => fmtNum(r.last) },
  { title: "UNIT", width: 17, text: (r) => r.unit, color: () => "dim" },
  { title: "PERIOD", width: 8, text: (r) => r.last_period ?? "", color: () => "dim" },
  // CHG is in percentage points ("pp") for a rate (unemployment, GDP growth) and CHG% stays empty there: see fmtChange.
  { title: "CHG", width: 10, align: "right", text: (r) => fmtChange(r.kind, r.chg, r.chg_pct).chg, color: (r) => signColor(r.chg) },
  { title: "CHG%", width: 8, align: "right", text: (r) => fmtChange(r.kind, r.chg, r.chg_pct).pct, color: (r) => signColor(r.chg) },
  { title: "NOTE", width: 40, text: (r) => r.notes[0] ?? "", color: () => "warn" },
];

const HISTORY: Column<PointRow>[] = [
  { title: "PERIOD", width: 10, text: (r) => r.period, color: () => "acc" },
  { title: "VALUE", width: 16, align: "right", text: (r) => (r.value == null ? "NO VALUE" : fmtNum(r.value)), color: (r) => (r.value == null ? "warn" : "fg") },
  { title: "CHG", width: 12, align: "right", text: (r) => fmtChange(r.kind, r.chg, r.pct).chg, color: (r) => signColor(r.chg) },
  { title: "CHG%", width: 9, align: "right", text: (r) => fmtChange(r.kind, r.chg, r.pct).pct, color: (r) => signColor(r.chg) },
];

/** Newest first; the change is against the period before it, and only when both have a value. */
function historyRows(s: UsSeries): PointRow[] {
  const out: PointRow[] = [];
  s.points.forEach(([period, value], i) => {
    const before = i > 0 ? s.points[i - 1][1] : null;
    const chg = value != null && before != null ? value - before : null;
    out.push({ kind: s.kind, period, value, chg, pct: chg != null && before ? (chg / Math.abs(before)) * 100 : null });
  });
  return out.reverse();
}

export default function USMAC({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parseUsmacArgs(args), [args]);
  // The effect depends on these plain values, not on `p`, so a new args array with the same words does not refetch.
  const { src, q, years, single, error: error0 } = p;
  const [env, setEnv] = useState<Envelope<UsMacroPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);

  const load = useCallback(
    (fresh: boolean) => {
      if (error0) return Promise.resolve();
      setLoading(true);
      return worldApi
        .usmac(src, q, years, fresh)
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
    [src, q, years, error0],
  );

  useEffect(() => {
    setDetail(null);
    void load(false);
  }, [load]);

  const d = env?.data;
  const series = useMemo(() => d?.series ?? [], [d]);
  const open = useMemo(() => {
    const id = detail ?? (single && series.length === 1 ? series[0].id : null);
    return series.find((s) => s.id === id) ?? null;
  }, [detail, single, series]);
  const hist = useMemo(() => (open ? historyRows(open) : []), [open]);
  const latest = useLatest({ series, open, count: open ? hist.length : series.length, canBack: detail !== null });

  useCsvExport(panelId, () => {
    if (!d) return null;
    return open ? gridCsv(`USMAC_${src}_${open.alias}`, HISTORY, hist) : gridCsv(`USMAC_${src}`, BOARD, series);
  });

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current;
        if (navKey(e, grid.current, cur.count)) return true;
        if (e.key === "Enter" && !cur.open) {
          const s = cur.series[grid.current?.selected() ?? -1];
          if (s) setDetail(s.id);
          return true;
        }
        if (e.key === "Backspace" && cur.canBack) {
          setDetail(null);
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  if (p.error) {
    return (
      <div className="fn">
        <div className="line"><span className="acc">USMAC</span> · {p.error}</div>
        <div className="dim">EXAMPLES: USMAC BLS CPI UNEMP · USMAC BEA GDPG · USMAC BEA INDUSTRY · USMAC CENSUS RETAIL AUTO · USMAC CENSUS TRADE CHINA 85</div>
      </div>
    );
  }
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">USMAC</span> {src}
        {d ? ` · ${open ? open.alias : `${series.length} SERIES`}` : ` ${q}`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {open ? (detail ? "BACKSPACE BOARD · " : "") : "ENTER HISTORY · "}E CSV · F5 REFRESH</span>
      </div>
      {open && (
        <div className="line">
          {open.label} <span className="dim">· {open.unit} · {open.freq === "M" ? "MONTHLY" : open.freq === "Q" ? "QUARTERLY" : open.freq === "A" ? "ANNUAL" : open.freq} · ID {open.id}</span>{" "}
          LAST <span className="acc">{fmtNum(open.last)}</span> ({open.last_period ?? "NO VALUE"})
          {open.kind === "rate" && <span className="dim"> · CHANGES IN PERCENTAGE POINTS (PP)</span>}
          {open.kind === "unknown" && <span className="warn"> · KIND UNKNOWN: PLAIN CHANGE ONLY, NO PERCENT</span>}
        </div>
      )}
      {d && <div className="dim">SOURCE: {d.source}. {d.note}</div>}
      {d && d.missing.length > 0 && <div className="warn">NOT RETURNED BY THE SOURCE: {d.missing.join(", ")}</div>}
      {d && d.messages.length > 0 && <div className="dim">SOURCE MESSAGE: {d.messages.join(" · ")}</div>}
      <ErrorLine error={error} hasData={!!d} usage="USMAC BLS CPI" />
      {!d && !error && loading && <div className="dim">LOADING…</div>}
      {d && (open ? <Grid key={`h:${open.id}`} ref={grid} columns={HISTORY} rows={hist} /> : <Grid key="board" ref={grid} columns={BOARD} rows={series} />)}
    </div>
  );
}
