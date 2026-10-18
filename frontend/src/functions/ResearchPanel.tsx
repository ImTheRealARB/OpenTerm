/**
 * Phase 13: the one panel behind every table function (EE, EEO, ANR, MGMT, SI, DVD, SPLT, CACS, IPO, EVTS, CN, ETF, MEMB,
 * MGR and the valuation tables). A function file is `export default makeResearchPanel({ fn: "ee" })`.
 * Keys: J/K move, V / Shift+V (or 1-9) pick the section, Enter opens the row's link, E exports the visible section, F5 refreshes.
 * Phase 14: a payload may carry `charts` (numeric-axis lines) and a `heat` map; they draw under the table, C cycles them, and
 * H/L/arrows... are left to the grid (the heat cursor moves with Shift+H J K L when the heat map is the visible visual).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type GridHandle } from "../components/Grid";
import { HeatMap, type HeatHandle } from "../components/HeatMap";
import { XYChart } from "../components/XYChart";
import { registerPanelKeys } from "../keys/panelKeys";
import { researchApi, type Envelope } from "../net/api";
import { gridColumns, cellText, type TablePayload, type TableRow } from "../research/tablePayload";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { ErrorLine, Header, openUrl, useEnvelope } from "./secPanel";
import { gridCsv, useCsvExport } from "./tableExport";

export interface ResearchOptions {
  /** Backend route name under /api/research (or /api/valuation, /api/deriv, /api/rates for `api`). */
  fn: string;
  valuation?: boolean;
  api?: "deriv" | "rates";
  /** Query parameters from the panel props; defaults to {symbol}. Return null to show `usage` instead of loading. */
  params?: (p: FunctionProps) => Record<string, string> | null;
  usage?: string;
  /** Short key hints appended to the header. */
  keys?: string;
}

export function makeResearchPanel(opts: ResearchOptions) {
  const defaultParams = (p: FunctionProps) => (p.security ? { symbol: p.security.symbol } : null);
  return function ResearchFunction(props: FunctionProps) {
    const { panelId } = props;
    const params = (opts.params ?? defaultParams)(props);
    const key = `${opts.fn}|${JSON.stringify(params)}`;
    const grid = useRef<GridHandle>(null);
    const heatRef = useRef<HeatHandle>(null);
    const [sec, setSec] = useState(0);
    const [vis, setVis] = useState(0);
    const { env, error, loading, reload } = useEnvelope<TablePayload>(key, (fresh) => {
      if (!params) return Promise.reject({ status: 400, message: opts.usage ?? "USAGE: SEE HELP" });
      const call = opts.api ? researchApi[opts.api] : opts.valuation ? researchApi.valuation : researchApi.get;
      return call(opts.fn, params, fresh) as Promise<Envelope<TablePayload>>;
    });
    const d = env?.data;
    const section = d?.sections[Math.min(sec, (d?.sections.length ?? 1) - 1)];
    const columns = useMemo(() => (section ? gridColumns(section) : []), [section]);
    const rows: TableRow[] = section?.rows ?? [];
    const visuals = useMemo(() => [...(d?.charts ?? []).map((c) => ({ kind: "chart" as const, c })), ...(d?.heat ? [{ kind: "heat" as const, h: d.heat }] : [])], [d]);
    const visual = visuals[Math.min(vis, visuals.length - 1)];
    const latest = useLatest({ rows, count: d?.sections.length ?? 0, visuals: visuals.length, heat: visual?.kind === "heat" });
    const label = opts.fn.toUpperCase();
    useCsvExport(panelId, () => (section ? gridCsv(`${label}_${d?.symbol ?? "ALL"}_${section.id.toUpperCase()}`, columns, rows) : null));

    useEffect(() => {
      setSec(0);
      setVis(0);
    }, [key]);
    useEffect(() => {
      grid.current?.moveTo(0);
    }, [section]);

    useEffect(
      () =>
        registerPanelKeys(panelId, (e) => {
          if (e.ctrlKey || e.altKey || e.metaKey) return false;
          if (e.key === "Shift" || e.key === "Control" || e.key === "Alt" || e.key === "Meta") return false;
          const { rows: cur, count, visuals: nvis, heat: heatShown } = latest.current;
          if (heatShown && e.shiftKey && "HJKL".includes(e.key)) {
            heatRef.current?.move(e.key === "J" ? 1 : e.key === "K" ? -1 : 0, e.key === "L" ? 1 : e.key === "H" ? -1 : 0);
            return true;
          }
          if (navKey(e, grid.current, cur.length)) return true;
          if (nvis > 1 && (e.key === "c" || e.key === "C")) {
            setVis((v) => (v + 1) % nvis);
            return true;
          }
          if (count > 1 && (e.key === "v" || e.key === "V")) {
            setSec((s) => (s + (e.key === "V" ? count - 1 : 1)) % count);
            return true;
          }
          const n = Number(e.key);
          if (n >= 1 && n <= count) {
            setSec(n - 1);
            return true;
          }
          if (e.key === "Enter") {
            const url = cur[grid.current?.selected() ?? -1]?.url;
            if (url) openUrl(url);
            return true;
          }
          if (e.key === "F5") {
            void reload(true);
            return true;
          }
          return false;
        }),
      [panelId, latest, reload, key],
    );

    return (
      <div className="fn">
        <Header
          title={d?.title ?? `${label}${props.security ? ` ${props.security.symbol}` : ""}`}
          env={env}
          loading={loading}
          keys={`J/K MOVE · ${d && d.sections.length > 1 ? "V SECTION · " : ""}${visuals.length > 1 ? "C CHART · " : ""}E CSV · F5 REFRESH${opts.keys ? ` · ${opts.keys}` : ""}`}
        />
        {d && d.headline.length > 0 && (
          <div className="line" data-testid="research-headline">
            {d.headline.map((h, i) => (
              <span key={h.label}>
                {i > 0 && <span className="dim"> · </span>}
                <span className="dim">{h.label} </span>
                {h.value}
              </span>
            ))}
          </div>
        )}
        {d && d.sections.length > 1 && (
          <div className="line" data-testid="research-tabs">
            {d.sections.map((s, i) => (
              <span key={s.id} className={i === sec ? "acc" : "dim"}>
                {i > 0 && " "}[{i + 1}] {s.title}
              </span>
            ))}
          </div>
        )}
        <ErrorLine error={error} hasData={!!env} />
        {d?.status?.startsWith("NOT RUNNABLE") && <div className="warn">{d.status}</div>}
        {d?.key_required.map((k) => (
          <div key={k.key} className="warn">
            KEY REQUIRED: set {k.key} in APIKEYS <span className="dim">· {k.what}</span>
          </div>
        ))}
        {section && rows.length === 0 && !error && <div className="warn">{section.note ?? `NO ROWS IN ${section.title}`}</div>}
        <Grid ref={grid} columns={columns} rows={rows} />
        {visual && (
          <div className="vis" data-testid="research-visual">
            <div className="line dim">
              {visual.kind === "chart" ? visual.c.title : visual.h.title}
              {visuals.length > 1 ? ` · ${Math.min(vis, visuals.length - 1) + 1}/${visuals.length} (C)` : ""}
              {visual.kind === "heat" ? " · SHIFT+H J K L MOVES THE CURSOR" : ""}
            </div>
            {visual.kind === "chart" ? <XYChart chart={visual.c} /> : <HeatMap ref={heatRef} heat={visual.h} />}
          </div>
        )}
        {section?.note && rows.length > 0 && <div className="summary dim">{section.note}</div>}
        {d?.notes.map((n) => (
          <div key={n} className="summary dim">
            {n}
          </div>
        ))}
      </div>
    );
  };
}

export { cellText };
