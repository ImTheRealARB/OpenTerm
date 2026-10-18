/**
 * WECO: G20 headline indicators (GDP growth, inflation, unemployment, central-government debt / GDP, current account / GDP) from the World Bank.
 * Every cell is that country's most recent value WITH ITS OWN DATA YEAR; years are never aligned or filled, and a cell older than two years is flagged.
 * Keys: 1-5 sort by a column (again = reverse), 0 by name, Enter opens ECST for the cell, E CSV, F5 refresh.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, worldApi, type Envelope, type WecoPayload, type WecoRow } from "../net/api";
import { navigate } from "../state/workspace";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { fmtCell, sortWeco } from "./worldArgs";

const SHORT: Record<string, string> = { GDPG: "GDP GRW %", CPI: "INFL %", UNEMP: "UNEMP %", DEBT: "DEBT/GDP %", CA: "CA/GDP %" };

export default function WECO({ panelId }: FunctionProps) {
  const [env, setEnv] = useState<Envelope<WecoPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState<{ col: number | "name"; desc: boolean }>({ col: "name", desc: false });
  const grid = useRef<GridHandle>(null);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return worldApi
      .weco(fresh)
      .then((e) => {
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => setError(e))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    void load(false);
  }, [load]);

  const d = env?.data;
  const aliases = useMemo(() => d?.columns.map((c) => c.alias) ?? [], [d]);
  const rows = useMemo(() => (d ? sortWeco(d.rows, aliases, sort.col, sort.desc) : []), [d, aliases, sort]);
  const latest = useLatest({ rows, aliases });

  const columns = useMemo<Column<WecoRow>[]>(
    () => [
      { title: "COUNTRY", width: 16, text: (r) => r.name.toUpperCase(), color: () => "acc" },
      ...aliases.map((a, i): Column<WecoRow> => ({
        title: `${i + 1} ${SHORT[a] ?? a}`, width: 15, align: "right",
        text: (r) => fmtCell(r.cells[a]),
        color: (r) => (r.cells[a]?.stale ? "warn" : r.cells[a] ? "fg" : "dim"),
      })),
    ],
    [aliases],
  );
  useCsvExport(panelId, () =>
    d ? gridCsv("WECO", [{ title: "ISO3", width: 4, text: (r: WecoRow) => r.iso3 }, ...columns,
      ...aliases.map((a): Column<WecoRow> => ({ title: `${a} YEAR`, width: 5, text: (r) => String(r.cells[a]?.year ?? "") }))], rows) : null,
  );

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.rows.length)) return true;
        if (e.key === "F5") {
          void load(true);
          return true;
        }
        if (e.key === "0" || (e.key >= "1" && e.key <= "5" && Number(e.key) <= cur.aliases.length)) {
          const col: number | "name" = e.key === "0" ? "name" : Number(e.key) - 1;
          setSort((s) => ({ col, desc: s.col === col ? !s.desc : col !== "name" }));
          return true;
        }
        if (e.key === "Enter") {
          const r = cur.rows[g?.selected() ?? -1];
          if (r) navigate(panelId, { fn: "ECST", args: [r.iso3, "CPI"], security: undefined });
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">WECO</span> G20 · {rows.length} COUNTRIES
        {d && <span className="dim"> · {d.source.toUpperCase()}</span>}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · 1-5 SORT COLUMN · 0 NAME · ENTER ECST (INFLATION) · E CSV · F5 REFRESH</span>
      </div>
      {d && <div className="dim">{d.note}. YELLOW = DATA OLDER THAN TWO YEARS. EMPTY = NO VALUE IN THE SOURCE.</div>}
      {d && d.failed.length > 0 && <div className="warn">{d.failed.map((f) => SHORT[f] ?? f).join(", ")} COLUMN DID NOT ANSWER: EMPTY BELOW. F5 RETRIES.</div>}
      <ErrorLine error={error} hasData={!!d} usage="WECO" />
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
