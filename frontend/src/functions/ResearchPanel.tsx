/**
 * Phase 13: the one panel behind every table function (EE, EEO, ANR, MGMT, SI, DVD, SPLT, CACS, IPO, EVTS, CN, ETF, MEMB,
 * MGR and the valuation tables). A function file is `export default makeResearchPanel({ fn: "ee" })`.
 * Keys: J/K move, V / Shift+V (or 1-9) pick the section, Enter opens the row's link, E exports the visible section, F5 refreshes.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { researchApi, type Envelope } from "../net/api";
import { gridColumns, cellText, type TablePayload, type TableRow } from "../research/tablePayload";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { ErrorLine, Header, openUrl, useEnvelope } from "./secPanel";
import { gridCsv, useCsvExport } from "./tableExport";

export interface ResearchOptions {
  /** Backend route name under /api/research (or /api/valuation when `valuation` is set). */
  fn: string;
  valuation?: boolean;
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
    const [sec, setSec] = useState(0);
    const { env, error, loading, reload } = useEnvelope<TablePayload>(key, (fresh) => {
      if (!params) return Promise.reject({ status: 400, message: opts.usage ?? "USAGE: SEE HELP" });
      const call = opts.valuation ? researchApi.valuation : researchApi.get;
      return call(opts.fn, params, fresh) as Promise<Envelope<TablePayload>>;
    });
    const d = env?.data;
    const section = d?.sections[Math.min(sec, (d?.sections.length ?? 1) - 1)];
    const columns = useMemo(() => (section ? gridColumns(section) : []), [section]);
    const rows: TableRow[] = section?.rows ?? [];
    const latest = useLatest({ rows, count: d?.sections.length ?? 0 });
    const label = opts.fn.toUpperCase();
    useCsvExport(panelId, () => (section ? gridCsv(`${label}_${d?.symbol ?? "ALL"}_${section.id.toUpperCase()}`, columns, rows) : null));

    useEffect(() => setSec(0), [key]);
    useEffect(() => {
      grid.current?.moveTo(0);
    }, [section]);

    useEffect(
      () =>
        registerPanelKeys(panelId, (e) => {
          if (e.ctrlKey || e.altKey || e.metaKey) return false;
          if (e.key === "Shift" || e.key === "Control" || e.key === "Alt" || e.key === "Meta") return false;
          const { rows: cur, count } = latest.current;
          if (navKey(e, grid.current, cur.length)) return true;
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
          keys={`J/K MOVE · ${d && d.sections.length > 1 ? "V SECTION · " : ""}E CSV · F5 REFRESH${opts.keys ? ` · ${opts.keys}` : ""}`}
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
        {d?.key_required.map((k) => (
          <div key={k.key} className="warn">
            KEY REQUIRED: set {k.key} in APIKEYS <span className="dim">· {k.what}</span>
          </div>
        ))}
        {section && rows.length === 0 && !error && <div className="warn">{section.note ?? `NO ROWS IN ${section.title}`}</div>}
        <Grid ref={grid} columns={columns} rows={rows} />
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
