/**
 * DEFI: DeFi yield pools from DefiLlama, cut on the server to pools with TVL over US$1M (the raw list never reaches the browser).
 * `DEFI` = the highest APYs overall, `DEFI ETHEREUM` = one chain (exact name), `DEFI AAVE` = projects whose name contains the text.
 * APY is the pool's own reported number (base + reward), not a forecast. Keys: arrows move, E CSV, F5 refresh.
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { worldApi, type DefiPool } from "../net/api";
import { joinArg } from "./cryptoArgs";
import { useEnvLoad } from "./cryptoLoad";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const pct = (v: number | null) => (v == null ? "" : v.toFixed(2) + "%");
const COLUMNS: Column<DefiPool>[] = [
  { title: "PROJECT", width: 20, text: (r) => r.project, color: () => "acc" },
  { title: "CHAIN", width: 12, text: (r) => r.chain },
  { title: "POOL", width: 22, text: (r) => r.symbol },
  { title: "TVL $", width: 9, align: "right", text: (r) => fmtBig(r.tvl) },
  { title: "APY", width: 8, align: "right", text: (r) => pct(r.apy), color: (r) => (r.apy >= 100 ? "warn" : "fg") },
  { title: "BASE", width: 8, align: "right", text: (r) => pct(r.apy_base), color: () => "dim" },
  { title: "REWARD", width: 8, align: "right", text: (r) => pct(r.apy_reward), color: () => "dim" },
  { title: "30D MEAN", width: 9, align: "right", text: (r) => pct(r.apy_30d), color: () => "dim" },
  { title: "STABLE", width: 6, text: (r) => (r.stable ? "YES" : ""), color: () => "dim" },
  { title: "IL RISK", width: 7, text: (r) => (r.il ?? "").toUpperCase(), color: (r) => (r.il === "yes" ? "warn" : "dim") },
];

export default function DEFI({ panelId, args }: FunctionProps) {
  const q = useMemo(() => joinArg(args), [args]);
  const { env, error, loading, load } = useEnvLoad((fresh) => worldApi.defi(q, fresh), q.toLowerCase());
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest({ rows });
  useCsvExport(panelId, () => (d ? gridCsv("DEFI", COLUMNS, rows) : null));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        if (navKey(e, grid.current, latest.current.rows.length)) return true;
        if (e.key === "F5") {
          void load(true);
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">DEFI</span> YIELD POOLS · {d ? (d.mode === "ALL" ? "ALL" : `${d.mode} ${(d.query ?? "").toUpperCase()}`) : q.toUpperCase() || "ALL"}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · E CSV · F5</span>
      </div>
      {d && (
        <div className="line" data-testid="defi-summary">
          {d.matched} POOLS MATCH OF {d.pools_over_tvl} WITH TVL OVER ${fmtBig(d.min_tvl)} · TOP {rows.length} BY APY
          <span className="dim"> · APY AS REPORTED BY EACH POOL, NOT A FORECAST · YELLOW = 100%+ OR IMPERMANENT-LOSS RISK</span>
        </div>
      )}
      <ErrorLine error={error} hasData={!!d} usage="DEFI [CHAIN|PROJECT]" />
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
