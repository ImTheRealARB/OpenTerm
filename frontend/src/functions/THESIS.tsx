/**
 * THESIS (Phase 16): investment thesis notes per ticker, stored locally (SQLite `theses`). Each note has a status (open, confirmed, invalidated, closed),
 * an invalidation rule (what would prove it wrong) and links to the stored SWARM / AI AUTO runs that support it (`SWARM REPLAY <id>`).
 * Commands: `THESIS [SYMBOL]`, `THESIS ADD <SYMBOL> <text>`, `THESIS INVALID <id> <rule>`. Keys: Up/Down or J/K select, S cycles the status, D D deletes.
 * The notes are yours; any text a model contributed says so in the note itself.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { registerPanelKeys } from "../keys/panelKeys";
import { replaceView } from "../state/workspace";
import type { FunctionProps } from "./registry";
import { nextStatus, thesisArgs } from "./thesisArgs";

interface Thesis {
  id: number;
  symbol: string;
  status: string;
  text: string;
  invalidation: string;
  run_ids: string[];
  created_at: number;
  updated_at: number;
}

const day = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);

export default function THESIS({ panelId, args }: FunctionProps) {
  const [rows, setRows] = useState<Thesis[]>([]);
  const [filter, setFilter] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  const [note, setNote] = useState<{ text: string; cls: string } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const state = useRef({ rows, sel, filter });
  state.current = { rows, sel, filter };
  const armed = useRef<number | null>(null);

  const load = useCallback(async (symbol: string | null, focusId?: number) => {
    try {
      const r = await fetch(`/api/theses${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`);
      if (r.ok) {
        const list = ((await r.json()) as { theses: Thesis[] }).theses;
        setRows(list);
        if (focusId !== undefined) setSel(Math.max(0, list.findIndex((t) => t.id === focusId)));
      } else setNote({ text: `HTTP ${r.status}`, cls: "err" });
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
    }
    setLoaded(true);
  }, []);

  const call = useCallback(async (method: string, url: string, body?: unknown) => {
    try {
      const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
      const j = await r.json().catch(() => null);
      if (!r.ok) setNote({ text: j?.error ?? `HTTP ${r.status}`, cls: "err" });
      return r.ok ? j : null;
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
      return null;
    }
  }, []);

  const asked = useRef(false);
  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    const a = thesisArgs(args);
    if (a.mode === "bad") setNote({ text: a.error, cls: "err" });
    if (a.mode === "list") {
      setFilter(a.symbol);
      void load(a.symbol);
    } else {
      void (async () => {
        if (a.mode === "add") {
          const j = await call("POST", "/api/theses", { symbol: a.symbol, text: a.text });
          if (j) setNote({ text: `THESIS ${j.thesis.id} ADDED FOR ${a.symbol}: THESIS INVALID ${j.thesis.id} <RULE> SETS WHAT WOULD PROVE IT WRONG`, cls: "up" });
          setFilter(a.symbol);
          await load(a.symbol, j?.thesis.id);
        } else if (a.mode === "invalid") {
          const j = await call("PATCH", `/api/theses/${a.id}`, { invalidation: a.text });
          if (j) setNote({ text: `INVALIDATION RULE SET FOR THESIS ${a.id}`, cls: "up" });
          await load(null, a.id);
        } else await load(null);
      })();
    }
    if (args.length) replaceView(panelId, (v) => ({ ...v, args: [] }));
  }, [args, panelId, load, call]);

  const cycle = useCallback(async () => {
    const { rows: rs, sel: i, filter: f } = state.current;
    const t = rs[i];
    if (!t) return;
    const j = await call("PATCH", `/api/theses/${t.id}`, { status: nextStatus(t.status) });
    if (j) setNote({ text: `THESIS ${t.id} IS NOW ${j.thesis.status.toUpperCase()}`, cls: "dim" });
    await load(f);
  }, [call, load]);

  const remove = useCallback(async () => {
    const { rows: rs, sel: i, filter: f } = state.current;
    const t = rs[i];
    if (!t) return;
    if (armed.current !== t.id) {
      armed.current = t.id;
      setNote({ text: `PRESS D AGAIN TO DELETE THESIS ${t.id} (${t.symbol})`, cls: "warn" });
      return;
    }
    armed.current = null;
    if (await call("DELETE", `/api/theses/${t.id}`)) setNote({ text: `THESIS ${t.id} DELETED`, cls: "dim" });
    setSel((s) => Math.max(0, s - 1));
    await load(f);
  }, [call, load]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey || e.key === "Shift") return false;
        const k = e.key.toLowerCase();
        if (k !== "d") armed.current = null;
        if (k === "arrowdown" || k === "j") setSel((s) => Math.min(state.current.rows.length - 1, s + 1));
        else if (k === "arrowup" || k === "k") setSel((s) => Math.max(0, s - 1));
        else if (k === "s") void cycle();
        else if (k === "d") void remove();
        else return false;
        return true;
      }),
    [panelId, cycle, remove],
  );

  const cur = rows[Math.min(sel, rows.length - 1)];
  return (
    <div className="fn" data-testid="thesis-panel">
      <div className="line">
        <span className="acc">THESIS</span> {filter ?? "ALL"}
        <span className="dim"> · {rows.length} NOTES · UP/DOWN SELECT · S STATUS · D D DELETE · THESIS ADD SYM TEXT · THESIS INVALID ID RULE</span>
      </div>
      {note && (
        <div className={note.cls} data-testid="thesis-note">
          {note.text}
        </div>
      )}
      {loaded && rows.length === 0 && <div className="dim">NO THESIS NOTES{filter ? ` FOR ${filter}` : ""}: THESIS ADD &lt;SYMBOL&gt; &lt;TEXT&gt;, OR T IN A SWARM RUN</div>}
      <div className="ai-log">
        {rows.map((t, i) => (
          <div key={t.id} className={i === Math.min(sel, rows.length - 1) ? "acc" : ""} data-testid="thesis-row" data-selected={i === Math.min(sel, rows.length - 1)}>
            {i === Math.min(sel, rows.length - 1) ? "> " : "  "}
            {String(t.id).padStart(3)} {t.symbol.padEnd(8)} {t.status.toUpperCase().padEnd(12)} {day(t.updated_at)} {t.text.slice(0, 90).replace(/\s+/g, " ")}
          </div>
        ))}
        {cur && (
          <div className="ai-turn" data-testid="thesis-detail">
            <div className="ai-answer">{cur.text}</div>
            <div className={cur.invalidation ? "" : "dim"}>
              <span className="dim">INVALIDATED IF: </span>
              {cur.invalidation || `NOT SET (THESIS INVALID ${cur.id} <RULE>)`}
            </div>
            <div className="dim">
              CREATED {day(cur.created_at)} · UPDATED {day(cur.updated_at)} · RUNS{" "}
              {cur.run_ids.length ? cur.run_ids.map((r) => `SWARM REPLAY ${r}`).join(" · ") : "NONE LINKED"}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
