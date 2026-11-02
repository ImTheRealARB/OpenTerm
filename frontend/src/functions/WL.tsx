/** Watchlists: `WL` lists them, `WL NAME` shows one as a live quote grid. Stored in SQLite. */
import { useEffect, useMemo, useRef, useState } from "react";
import { prefillCommand } from "../components/CommandLine";
import { PanelNote } from "../components/PanelNote";
import { Grid, type GridHandle } from "../components/Grid";
import { deleteWatchlist, editWatchlist, putWatchlist, refreshWatchlists, watchlistList, watchlistVersion } from "../command/watchlists";
import { registerPanelKeys } from "../keys/panelKeys";
import { api, type ApiError } from "../net/api";
import { LAYOUT_NAME_RE } from "../state/layoutState";
import { useStore } from "../state/store";
import { navigate } from "../state/workspace";
import { liveSymbol, navKey, QUOTE_COLUMNS as COLUMNS, SORTS, sortRows, useLatest, useLiveRows, useQuotes, type Sort } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { listNav } from "./listNav";

const when = (t: number) => {
  const d = new Date(t * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export default function WL({ panelId, args }: FunctionProps) {
  const name = args[0]?.toUpperCase();
  if (!name) return <WatchlistIndex panelId={panelId} />;
  if (!LAYOUT_NAME_RE.test(name))
    return (
      <PanelNote kind="error" hint="Example: WL TECH, or WL INDIA ADD RELIANCE.NS. Names are letters, digits, underscore, dot and dash.">
        WATCHLIST NAME: 1-32 OF A-Z 0-9 _ . -
      </PanelNote>
    );
  return <WatchlistView key={name} panelId={panelId} name={name} />;
}

function WatchlistView({ panelId, name }: { panelId: number; name: string }) {
  const version = useStore(watchlistVersion, (v) => v);
  const [symbols, setSymbols] = useState<string[] | null>(null);
  const [missing, setMissing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [sort, setSort] = useState<Sort>("INPUT");
  const undo = useRef<string[] | null>(null);
  const grid = useRef<GridHandle>(null);

  useEffect(() => {
    let alive = true;
    api
      .watchlist(name)
      .then((w) => {
        if (!alive) return;
        setSymbols(w.symbols);
        setMissing(false);
        setErr(null);
      })
      .catch((e: ApiError) => {
        if (!alive) return;
        if (e.status === 404) {
          setSymbols([]);
          setMissing(true);
        } else setErr(e.message);
      });
    return () => {
      alive = false;
    };
  }, [name, version, reload]);

  // Same symbols, same array: a refetch that changed nothing does not re-request quotes.
  const key = (symbols ?? []).join(",");
  const inputs = useMemo(() => (key ? key.split(",") : []), [key]);
  const { rows, setRows, loading } = useQuotes(inputs, reload);
  const latest = useLatest({ rows, sort, symbols });

  useLiveRows(rows, grid, liveSymbol);
  useCsvExport(panelId, () => gridCsv(`WL_${name}`, COLUMNS, rows));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, sort: curSort, symbols: list } = latest.current;
        if (navKey(e, g, cur.length)) return true;
        const r = cur[g?.selected() ?? -1];
        switch (e.key) {
          case "Enter":
            if (r) navigate(panelId, { fn: "DES", security: { symbol: r.symbol }, args: [] });
            return true;
          case "a":
            prefillCommand(`WL ${name} ADD `);
            return true;
          case "d":
          case "Delete":
            if (!r || !list) return true;
            undo.current = list;
            setSymbols(list.filter((s) => s !== r.input)); // optimistic; the PATCH result refetches
            void editWatchlist(name, [], [r.input], `REMOVED ${r.input} FROM ${name}. U UNDOES.`);
            return true;
          case "u":
            if (undo.current) {
              const before = undo.current;
              undo.current = null;
              setSymbols(before);
              void putWatchlist(name, before);
            }
            return true;
          case "s": {
            const next = SORTS[(SORTS.indexOf(curSort) + 1) % SORTS.length];
            setSort(next);
            setRows(sortRows(cur, next, inputs));
            return true;
          }
          case "F5":
            setReload((n) => n + 1);
            return true;
        }
        return false;
      }),
    [panelId, name, inputs, latest, setRows],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">WATCHLIST {name}</span> <b className="pv">{rows.length}</b> SECURITIES · <span className="dim">SORT</span> {sort}
        {(loading || (symbols === null && !err)) && <span className="dim"> · LOADING…</span>}
        {/* With a list on screen the error means the data is old; with none, the PanelNote below carries it. */}
        {err && symbols !== null && <span className="err"> · STALE: {err}</span>}
        <span className="dim"> · J/K MOVE · ENTER DES · A ADD · D REMOVE · U UNDO · S SORT · E CSV · F5 REFRESH</span>
      </div>
      {err && symbols === null && (
        <PanelNote kind="error" hint="The list could not be read, so nothing is shown. Press F5 to retry.">
          WATCHLIST {name} UNAVAILABLE: {err}
        </PanelNote>
      )}
      {missing && (
        <PanelNote kind="empty" hint={`Create it: WL ${name} ADD AAPL MSFT, or press A and type the symbols (GUI mode: the Add button).`}>
          NO WATCHLIST {name}. WL {name} ADD AAPL MSFT CREATES IT.
        </PanelNote>
      )}
      {!missing && symbols?.length === 0 && (
        <PanelNote kind="empty" hint={`Add one: WL ${name} ADD AAPL, or press A and type the symbols (GUI mode: the Add button).`}>
          EMPTY. A ADDS SYMBOLS (WL {name} ADD SYM...).
        </PanelNote>
      )}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}

/** `WL` with no name: saved lists, keyboard driven (same keys as the LAYOUT list). */
function WatchlistIndex({ panelId }: { panelId: number }) {
  const list = useStore(watchlistList, (l) => l);
  const [sel, setSel] = useState(0);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const state = useLatest({ list, sel, confirm });
  useCsvExport(panelId, () =>
    list ? { name: "WATCHLISTS", header: ["NAME", "SYMBOLS", "UPDATED_UTC"], rows: list.map((w) => [w.name, w.count, new Date(w.updated_at * 1000).toISOString().slice(0, 16).replace("T", " ")]) } : null,
  );

  const refresh = () =>
    refreshWatchlists()
      .then(() => setErr(null))
      .catch((e: ApiError) => setErr(e.message));

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { list: l, sel: i, confirm: c } = state.current;
        const n = l?.length ?? 0;
        const name = l?.[Math.min(i, n - 1)]?.name;
        if (c && e.key !== "Delete" && e.key !== "x") setConfirm(null);
        // Phase 10: g / G / Home / End / PgUp / PgDn too (vim Ctrl+D / Ctrl+U arrive as PgDn / PgUp).
        const to = /^[jk]$|^Arrow(Up|Down)$/.test(e.key) ? null : listNav(e.key, i, n);
        if (to !== null) {
          setSel(to);
          return true;
        }
        switch (e.key) {
          case "j":
          case "ArrowDown":
            setSel(Math.min(n - 1, i + 1));
            return true;
          case "k":
          case "ArrowUp":
            setSel(Math.max(0, i - 1));
            return true;
          case "Enter":
            if (name) navigate(panelId, { fn: "WL", args: [name] });
            return true;
          case "Delete":
          case "x":
            if (!name) return true;
            if (c === name) {
              setConfirm(null);
              void deleteWatchlist(name);
            } else setConfirm(name);
            return true;
          case "n":
            prefillCommand("WL ");
            return true;
          case "F5":
            void refresh();
            return true;
          case "Escape":
            return c !== null;
        }
        return false;
      }),
    [panelId, state],
  );

  if (!list)
    return err ? (
      <PanelNote kind="error" hint="The saved lists could not be read. Press F5 to retry.">
        WATCHLISTS UNAVAILABLE: {err}
      </PanelNote>
    ) : (
      <PanelNote kind="loading">LOADING…</PanelNote>
    );
  const i = Math.min(sel, list.length - 1);
  return (
    <div>
      <h2>
        WATCHLISTS {err && <span className="err">STALE: {err}</span>}
      </h2>
      {list.length === 0 ? (
        <PanelNote kind="empty" hint="Create one: WL TECH ADD AAPL MSFT NVDA (any name), or press N to start the command.">
          NO WATCHLISTS. WL NAME ADD AAPL MSFT CREATES ONE.
        </PanelNote>
      ) : (
        <table className="t wl-index">
          <colgroup>
            <col style={{ width: 20 }} />
            <col style={{ width: 260 }} />
            <col style={{ width: 80 }} />
            <col style={{ width: 140 }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th />
              <th>NAME</th>
              <th className="n">SYMBOLS</th>
              <th>UPDATED</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((w, k) => (
              <tr key={w.name} className={k === i ? "on" : ""} aria-selected={k === i}>
                <td className="acc">{k === i ? ">" : ""}</td>
                <td>{w.name}</td>
                <td className="n">{w.count}</td>
                <td className="dim">{when(w.updated_at)}</td>
                <td>{confirm === w.name && <span className="err">DELETE? PRESS DEL AGAIN</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="dim">J K / ↑ ↓ SELECT · ENTER OPEN · DEL DELETE · N NEW · F5 REFRESH · WL NAME ADD|RM SYM...</div>
    </div>
  );
}
