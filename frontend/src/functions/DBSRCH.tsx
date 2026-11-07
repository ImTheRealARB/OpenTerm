/**
 * DBSRCH: find a DBnomics series by words, then open it in ECST.
 *
 * DBnomics (keyless) mirrors statistics from the IMF, OECD, Eurostat, BIS, ECB, World Bank and national statistics offices. ECST can plot any of
 * its series (`ECST DBN:<provider>/<dataset>/<series>`), but the ids are impossible to guess, so this panel searches in two steps:
 *   1. `DBSRCH france inflation`            lists DATASETS (one table of a provider); Enter lists the matching series inside the highlighted one.
 *   2. `DBSRCH DS:BDF/ICP france inflation` lists the SERIES; Enter opens the highlighted one in this same panel as ECST.
 * The whole state (words, dataset, page) lives in the panel's args, so the global Back key returns to the same list.
 * Every row names the ORIGINAL data provider: DBnomics only mirrors it, so cite the provider. The last period of a series is not in the
 * search answer; the chart shows it. Keys: arrows move, Enter go deeper, N/P next/previous page, B back to the datasets, E CSV, F5 refresh.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { DbsDatasetRow, DbsSeriesRow } from "../net/types";
import { worldApi } from "../net/worldApi";
import { navigate, replaceView } from "../state/workspace";
import { useEnvelope } from "./useEnvelope";
import { buildDbsrchArgs, count, DATASET_PAGE, DBSRCH_USAGE, hasNext, pageText, parseDbsrchArgs, prevOffset, SERIES_PAGE } from "./dbsrchArgs";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const DATASETS: Column<DbsDatasetRow>[] = [
  { title: "PROVIDER", width: 9, text: (r) => r.provider, color: () => "acc" },
  { title: "DATASET", width: 34, text: (r) => r.dataset },
  { title: "NAME", width: 52, text: (r) => r.name },
  { title: "MATCHING", width: 10, align: "right", text: (r) => count(r.matching) },
  { title: "SERIES", width: 10, align: "right", text: (r) => count(r.series), color: () => "dim" },
  { title: "UPDATED", width: 11, text: (r) => r.updated ?? "", color: () => "dim" },
  { title: "ORIGINAL PROVIDER", width: 48, text: (r) => r.provider_name, color: () => "dim" },
];
const SERIES: Column<DbsSeriesRow>[] = [
  { title: "SERIES", width: 46, text: (r) => r.series, color: () => "acc" },
  { title: "NAME", width: 80, text: (r) => r.name },
  { title: "FREQ", width: 17, text: (r) => r.freq, color: () => "dim" },
  { title: "INDEXED", width: 11, text: (r) => r.indexed ?? "", color: () => "dim" },
  { title: "ECST", width: 5, text: (r) => (r.ref ? "OK" : "NO"), color: (r) => (r.ref ? "dim" : "warn") },
];

export default function DBSRCH({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parseDbsrchArgs(args), [args]);
  if (p.error) {
    return (
      <div className="fn">
        <div className="line"><span className="acc">DBSRCH</span> · {p.error}</div>
        <div className="dim">EXAMPLES: DBSRCH FRANCE INFLATION · DBSRCH OECD UNEMPLOYMENT · DBSRCH DS:ECB/CSEC FRANCE</div>
      </div>
    );
  }
  return <DbsrchView panelId={panelId} q={p.q} dataset={p.dataset} offset={p.offset} />;
}

function DbsrchView({ panelId, q, dataset, offset }: { panelId: number; q: string; dataset: string; offset: number }) {
  const { env, error, loading, reload: load } = useEnvelope(`${q.toLowerCase()}|${dataset}|${offset}`, (fresh) => worldApi.dbsearch(q, dataset, offset, fresh));
  const [notice, setNotice] = useState("");
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const datasets = d?.mode === "DATASETS" ? d.items : null;
  const series = d?.mode === "SERIES" ? d.items : null;
  const page = dataset ? SERIES_PAGE : DATASET_PAGE;
  const rows = datasets?.length ?? series?.length ?? 0;
  const latest = useLatest({ datasets, series, q, dataset, offset, page, total: d?.total ?? 0, rows });
  useCsvExport(panelId, () => {
    if (datasets) return gridCsv("DBSRCH_DATASETS", DATASETS, datasets);
    return series && d?.mode === "SERIES" ? gridCsv(`DBSRCH_${d.provider}_${d.dataset}`, SERIES, series) : null;
  });

  useEffect(() => {
    setNotice("");
  }, [q, dataset, offset]);

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current;
        const g = grid.current;
        if (navKey(e, g, cur.rows)) return true;
        const toPage = (to: number) => replaceView(panelId, (v) => ({ ...v, args: buildDbsrchArgs({ q: cur.q, dataset: cur.dataset, offset: to }) }));
        switch (e.key) {
          case "n":
          case "N":
            if (hasNext(cur.offset, cur.rows, cur.total)) toPage(cur.offset + cur.page);
            return true;
          case "p":
          case "P": {
            const to = prevOffset(cur.offset, cur.page);
            if (to != null) toPage(to);
            return true;
          }
          case "b":
          case "B":
          case "Backspace":
            // From a series list back to the datasets for the same words.
            if (cur.dataset) navigate(panelId, { fn: "DBSRCH", args: buildDbsrchArgs({ q: cur.q, dataset: "", offset: 0 }), security: undefined });
            return !!cur.dataset;
          case "Enter": {
            const i = g?.selected() ?? -1;
            if (cur.datasets) {
              const r = cur.datasets[i];
              if (r) navigate(panelId, { fn: "DBSRCH", args: buildDbsrchArgs({ q: cur.q, dataset: `${r.provider}/${r.dataset}`, offset: 0 }), security: undefined });
            } else if (cur.series) {
              const r = cur.series[i];
              if (r?.ref) navigate(panelId, { fn: "ECST", args: [r.ref], security: undefined });
              else if (r) setNotice(`ECST CANNOT OPEN THIS ID (UNSUPPORTED CHARACTERS): ${r.series}`);
            }
            return true;
          }
        }
        return false;
      }),
    [panelId, latest],
  );

  const total = d?.total ?? 0;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">DBSRCH</span> {dataset ? `SERIES IN ${dataset}` : "DATASETS"}
        {q && <span> · "{q.toUpperCase()}"</span>}
        {d && <span className="dim"> · {pageText(offset, rows, total)}</span>}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {dataset ? "ENTER OPEN IN ECST · B DATASETS" : "ENTER LIST SERIES"} · N/P PAGE · E CSV · F5</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage={DBSRCH_USAGE} />
      {d?.mode === "SERIES" && (
        <div className="line">
          {d.dataset_name} <span className="dim">({d.provider}/{d.dataset}) · DBNOMICS MIRRORS {d.provider}'S DATA: CITE {d.provider}, NOT DBNOMICS</span>
        </div>
      )}
      {d?.mode === "DATASETS" && <div className="dim">{d.note}</div>}
      {d?.mode === "SERIES" && <div className="dim">LAST PERIOD SHOWS ON THE CHART.</div>}
      {notice && <div className="warn">{notice}</div>}
      {d && rows === 0 && <div className="warn">NO MATCH{q ? ` FOR "${q.toUpperCase()}"` : ""}{offset > 0 ? " ON THIS PAGE (P GOES BACK)" : ""}. TRY FEWER OR DIFFERENT WORDS: EVERY WORD MUST MATCH.</div>}
      {datasets ? <Grid key="datasets" ref={grid} columns={DATASETS} rows={datasets} /> : series ? <Grid key="series" ref={grid} columns={SERIES} rows={series} /> : null}
    </div>
  );
}
