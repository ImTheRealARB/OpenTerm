/** US market movers from Nasdaq.com: gainers, losers, most active (shares / dollars), Nasdaq-100. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtBig, fmtChg, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, type Envelope, type Mover, type MoversPayload } from "../net/api";
import { navigate } from "../state/workspace";
import { dirColor, navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const TABS = [
  ["GAINERS", "GAINERS"],
  ["LOSERS", "LOSERS"],
  ["ACTIVE", "MOST ACTIVE"],
  ["DOLLAR", "$ VOLUME"],
  ["NDX100", "NASDAQ-100"],
] as const;
type Tab = (typeof TABS)[number][0];
const POLL_MS = 60_000;

const COLUMNS: Column<Mover>[] = [
  { title: "SECURITY", width: 8, text: (r) => r.symbol, color: () => "acc" },
  { title: "NAME", width: 34, text: (r) => r.name ?? "", color: () => "dim" },
  { title: "LAST", width: 11, align: "right", text: (r) => fmtPrice(r.price) },
  { title: "CHG", width: 10, align: "right", text: (r) => fmtChg(r.change), color: (r) => dirColor(r.change) },
  { title: "%CHG", width: 9, align: "right", text: (r) => fmtPct(r.change_pct), color: (r) => dirColor(r.change_pct) },
  { title: "VOLUME", width: 9, align: "right", text: (r) => fmtBig(r.volume) },
];

const tabFrom = (args: string[]): Tab => {
  const a = args[0]?.toUpperCase();
  return (TABS.find(([k, label]) => k === a || label.startsWith(a ?? "\0"))?.[0] ?? "GAINERS") as Tab;
};

export default function MOV({ panelId, args }: FunctionProps) {
  const [tab, setTab] = useState<Tab>(() => tabFrom(args));
  const [env, setEnv] = useState<Envelope<MoversPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const grid = useRef<GridHandle>(null);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return api
      .movers(fresh)
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

  const rows = useMemo(() => env?.data.tables[tab] ?? [], [env, tab]);
  const latest = useLatest({ rows, tab });
  useCsvExport(panelId, () => gridCsv(`MOV_${tab}`, COLUMNS, rows));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, tab: t } = latest.current;
        if (navKey(e, g, cur.length)) return true;
        const n = Number(e.key);
        if (n >= 1 && n <= TABS.length) {
          setTab(TABS[n - 1][0]);
          g?.moveTo(0);
          return true;
        }
        switch (e.key) {
          case "Tab": {
            const i = TABS.findIndex(([k]) => k === t);
            setTab(TABS[(i + (e.shiftKey ? TABS.length - 1 : 1)) % TABS.length][0]);
            return true;
          }
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (r) navigate(panelId, { fn: "DES", security: { symbol: r.symbol }, args: [] });
            return true;
          }
          case "F5":
            void load(true);
            return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const asOf = env?.data.table_as_of[tab] ?? env?.data.as_of_text;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">US MOVERS</span>
        {env && ` · ${(env.source ?? "").toUpperCase()}`}
        {asOf && <span> · {asOf.toUpperCase()}</span>}
        {env?.stale && <span className="warn"> · STALE {fmtAge(env.age_s)}</span>}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim"> · 1-5 / TAB SWITCH · J/K MOVE · ENTER DES · E CSV · F5 REFRESH</span>
      </div>
      <div className="tabs">
        {TABS.map(([k, label], i) => (
          <span key={k} className={k === tab ? "on" : "dim"}>
            {i + 1} {label}
          </span>
        ))}
      </div>
      {error && (
        <div className="err">
          {error.message}
          {error.detail && <span className="dim"> ({error.detail})</span>}
        </div>
      )}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
