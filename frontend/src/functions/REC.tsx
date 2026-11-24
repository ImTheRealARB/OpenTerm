/**
 * REC (Phase 24): the optional recorder for crypto trades and order-book snapshots.
 *
 *   REC                    running recordings + stored sessions
 *   REC BTCUSDT ON | OFF   start / stop recording that pair
 *
 * OFF BY DEFAULT: nothing records until you type `REC <SYMBOL> ON`. Files stay on this computer only (`<db folder>/recordings`).
 * Limits: SETTINGS RECORDER CAP <MB> | DAYS <n>. Keys: arrows move, Enter opens FOOT on the session, T = TAS, M = DOM (the order book),
 * S stops a running recording, D twice deletes a stored session, F5 refreshes. Crypto only (Binance spot pairs).
 * `FOOT BTCUSDT REC=<id>`, `TAS ... REC=<id>` and `DOM ... REC=<id>` show a session instead of live data.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtNum } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { recorderApi } from "../net/recorderApi";
import type { RecListing, RecSession } from "../net/recorderTypes";
import { useLatest } from "../state/useLatest";
import { navigate, replaceView } from "../state/workspace";
import { fmtBytes, parseRecArgs, recDate, stampOf } from "./recArgs";
import { usePanelRefresh } from "./panelRefresh";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const POLL_MS = 3_000; // a running recording grows: look again every 3 s

/** One grid row: a stored session, with live counters when it is still recording. */
interface Row extends RecSession {
  trades: number | null;
  snapshots: number | null;
  errors: number;
}

const COLUMNS: Column<Row>[] = [
  { title: "STATE", width: 10, text: (r) => (r.recording ? "RECORDING" : "STORED"), color: (r) => (r.recording ? "up" : "dim") },
  { title: "SYMBOL", width: 10, text: (r) => r.symbol },
  { title: "SESSION ID", width: 18, text: (r) => stampOf(r.id), color: () => "acc" },
  { title: "DATE UTC", width: 11, text: (r) => recDate(r.started), color: () => "dim" },
  { title: "TRADES", width: 10, align: "right", text: (r) => (r.trades == null ? "" : fmtNum(r.trades, 0)) },
  { title: "BOOKS", width: 8, align: "right", text: (r) => (r.snapshots == null ? "" : fmtNum(r.snapshots, 0)) },
  { title: "SIZE", width: 10, align: "right", text: (r) => fmtBytes(r.bytes), color: () => "dim" },
  { title: "SKIPPED", width: 8, align: "right", text: (r) => (r.errors ? String(r.errors) : ""), color: () => "warn" },
];

/** Stored sessions with the running recordings' counters merged in (newest first, as the server sorts them). */
function rowsOf(l: RecListing | null): Row[] {
  if (!l) return [];
  const live = new Map(l.active.map((a) => [a.id, a]));
  return l.sessions.map((s) => {
    const a = live.get(s.id);
    return { ...s, trades: a ? a.trades : null, snapshots: a ? a.snapshots : null, errors: a ? a.errors : 0 };
  });
}

export default function REC({ panelId, args }: FunctionProps) {
  const a = useMemo(() => parseRecArgs(args), [args]);
  const [listing, setListing] = useState<RecListing | null>(null);
  const [error, setError] = useState<string | null>(a.error ?? null);
  const [note, setNote] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);
  const rows = useMemo(() => rowsOf(listing), [listing]);
  const latest = useLatest({ rows, confirm });

  const refresh = useCallback(async () => {
    try {
      setListing(await recorderApi.list());
      setError((e) => (e && e.startsWith("COULD NOT LIST") ? null : e));
    } catch (e) {
      setError(`COULD NOT LIST RECORDINGS: ${(e as Error).message}`);
    }
  }, []);

  // Look now and then every 3 s while the panel is open.
  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  // `REC BTCUSDT ON|OFF` runs once per command (by args identity). The command is the user's explicit start: nothing else starts a recording.
  const done = useRef<unknown>(null);
  useEffect(() => {
    if (done.current === args || a.action === "LIST") return;
    done.current = args;
    // Forget the command in the saved view: a layout that restores this panel later must never start (or stop) a recording by itself.
    replaceView(panelId, (v) => ({ ...v, args: [] }));
    void (async () => {
      try {
        if (a.action === "ON") {
          const r = await recorderApi.start(a.sym);
          setNote(`RECORDING ${r.symbol} AS ${stampOf(r.id)} (REC ${r.symbol} OFF TO STOP)`);
        } else {
          const r = await recorderApi.stop(a.sym);
          setNote(`STOPPED ${a.sym}: ${fmtNum(r.trades, 0)} TRADES, ${fmtNum(r.snapshots, 0)} BOOKS KEPT AS ${stampOf(r.id)}`);
        }
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      }
      await refresh();
    })();
  }, [args, a.action, a.sym, panelId, refresh]);

  useCsvExport(panelId, () => gridCsv("REC", COLUMNS, rows));
  usePanelRefresh(panelId, () => void refresh());

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, confirm: c } = latest.current;
        const r = cur[g?.selected() ?? -1];
        // Any key except the second D forgets a pending delete.
        if (c && !(c === r?.id && (e.key === "d" || e.key === "Delete"))) setConfirm(null);
        if (navKey(e, g, cur.length)) return true;
        const open = (fn: "FOOT" | "TAS" | "DOM") => {
          if (r) navigate(panelId, { fn, args: [r.symbol, `REC=${stampOf(r.id)}`] });
          return true;
        };
        switch (e.key) {
          case "Enter":
            return open("FOOT");
          case "t":
            return open("TAS");
          case "m":
            return open("DOM");
          case "s":
            if (r?.recording) {
              void recorderApi
                .stop(r.symbol)
                .then(() => setNote(`STOPPED ${r.symbol}`))
                .catch((err: Error) => setError(err.message))
                .finally(() => void refresh());
            }
            return true;
          case "d":
          case "Delete":
            if (!r) return true;
            if (r.recording) {
              setError("THIS SESSION IS RECORDING: PRESS S TO STOP IT FIRST");
            } else if (c === r.id) {
              setConfirm(null);
              void recorderApi
                .remove(r.id)
                .then(() => setNote(`DELETED ${r.id}`))
                .catch((err: Error) => setError(err.message))
                .finally(() => void refresh());
            } else setConfirm(r.id);
            return true;
          case "Escape":
            return c !== null;
        }
        return false;
      }),
    [panelId, latest, refresh],
  );

  const stopped = listing ? Object.entries(listing.notes) : [];
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">REC</span> RECORDER · <span data-testid="rec-label-off">OFF BY DEFAULT · KEPT ON THIS COMPUTER ONLY</span>
        <span className="dim"> · ENTER FOOT · T TAS · M DOM · S STOP · D D DELETE · F5</span>
      </div>
      {listing && (
        <div className="line dim" data-testid="rec-summary">
          {listing.active.length} RECORDING · {listing.sessions.length} SESSIONS · {fmtBytes(listing.total_bytes)} OF {listing.cap_mb} MB CAP · KEPT {listing.retention_days} DAYS · EVERY {listing.poll_s}S · START: REC BTCUSDT ON
        </div>
      )}
      {stopped.map(([sym, why]) => (
        <div key={sym} className="line warn">
          RECORDER STOPPED: {why} ({sym})
        </div>
      ))}
      {confirm && <div className="line warn">DELETE {confirm}? PRESS D AGAIN (ANY OTHER KEY CANCELS)</div>}
      {note && <div className="line" data-testid="rec-note">{note}</div>}
      {error && <div className="line err">{error}</div>}
      {listing && rows.length === 0 && !error && <div className="line dim">NOTHING RECORDED YET. TYPE REC BTCUSDT ON TO START (CRYPTO ONLY).</div>}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
