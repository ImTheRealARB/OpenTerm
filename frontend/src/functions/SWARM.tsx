/**
 * SWARM (Phase 16): preset multi-agent runs. A fixed set of analyst roles each answer from their own tools, then the chair writes the synthesis.
 * Every role shows its tool calls (source, age), its answer with [T1] citations and its own UNGROUNDED / UNSOURCED verdict; the chair's numbers are checked
 * against the analysts' notes. A failed role is retried once and shown if it still fails. Runs are stored: `SWARM REPLAY <id>` shows one again with no model call.
 * Keys: Esc cancels a running swarm, T saves the final answer as a THESIS note for the subject's ticker (linked to this run), X clears. Model output, not data.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { registerPanelKeys } from "../keys/panelKeys";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { replaceView } from "../state/workspace";
import { Answer, ToolLines } from "./AI";
import { citeSegments, parseSse } from "./aiStream";
import type { FunctionProps } from "./registry";
import { subjectSymbol, swarmArgs } from "./swarmArgs";
import { newSwarm, reduceSwarm, type RoleState, type SwarmEvent, type SwarmState } from "./swarmStream";
import { watchPanelGone } from "./panelGoneWatch";

interface Preset {
  code: string;
  title: string;
  roles: { id: string; title: string; tools: string[] }[];
  note: string;
}
interface StoredRun {
  id: string;
  kind: string;
  title: string;
  symbol: string | null;
  created_at: number;
}

const STATE_LABEL: Record<RoleState["state"], string> = { waiting: "WAITING", running: "RUNNING", done: "DONE", failed: "FAILED" };

function RoleView({ r }: { r: RoleState }) {
  const t = r.turn;
  return (
    <div className="ai-turn" data-testid="swarm-role" data-role={r.id}>
      <div>
        <span className="acc">{r.title.toUpperCase()}</span>
        <span className="dim">
          {" "}
          · {STATE_LABEL[r.state]}
          {r.attempt > 1 ? ` · ATTEMPT ${r.attempt}` : ""} · TOOLS {r.tools.join(" ")}
        </span>
      </div>
      <ToolLines tools={t.tools} />
      {r.errors.map((e, i) => (
        <div key={i} className="warn" data-testid="swarm-role-error">
          {e}
        </div>
      ))}
      {t.notices.map((n, i) => (
        <div key={i} className="warn">
          {n}
        </div>
      ))}
      {(t.answer || r.state === "running") && <Answer text={t.answer} running={r.state === "running"} />}
      {r.state === "done" && t.label && <div className="warn">{t.label}: THIS ROLE USED NO TOOL DATA</div>}
      {r.state === "done" && t.unsourced.length > 0 && <div className="warn">UNSOURCED NUMBERS (NO TOOL RETURNED THEM): {t.unsourced.join(" ")}</div>}
    </div>
  );
}

export default function SWARM({ panelId, args }: FunctionProps) {
  const ai = useStore(settingsStore, (s) => s.ai);
  const [run, setRun] = useState<SwarmState | null>(null);
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [stored, setStored] = useState<StoredRun[]>([]);
  const [note, setNote] = useState<{ text: string; cls: string } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const state = useRef({ run, ai });
  state.current = { run, ai };
  const log = useRef<HTMLDivElement>(null);

  const loadLists = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([fetch("/api/ai/swarm/presets"), fetch("/api/ai/runs?kind=swarm")]);
      if (p.ok) setPresets(((await p.json()) as { presets: Preset[] }).presets);
      if (r.ok) setStored(((await r.json()) as { runs: StoredRun[] }).runs);
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
    }
  }, []);

  const stream = useCallback(async (url: string, body: unknown) => {
    const ac = new AbortController();
    abort.current = ac;
    // Stop the (paid) run if this panel is closed. A maximize remount does not count as closing.
    const unwatch = watchPanelGone(panelId, () => ac.abort());
    let cur = newSwarm();
    setRun(cur);
    const apply = (e: SwarmEvent) => {
      cur = reduceSwarm(cur, e);
      setRun(cur);
    };
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), signal: ac.signal });
      if (!res.ok || !res.body) {
        const j = await res.json().catch(() => null);
        apply({ type: "error", kind: j?.kind ?? "http", text: j?.error ?? `HTTP ${res.status}` });
        return;
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parsed = parseSse<SwarmEvent>(buf);
        buf = parsed.rest;
        parsed.events.forEach(apply);
      }
      if (cur.status === "running") setRun({ ...cur, status: "done", final: { answer: "", unsourced: [], grounded: false, label: "INCOMPLETE", failed: [] } });
    } catch (e) {
      if ((e as Error).name === "AbortError") setRun({ ...cur, status: "done", final: { answer: "", unsourced: [], grounded: false, label: "INCOMPLETE", failed: [] } });
      else apply({ type: "error", kind: "network", text: "BACKEND DOWN" });
    } finally {
      unwatch();
      abort.current = null;
      void loadLists();
    }
  }, [loadLists, panelId]);

  const asked = useRef(false);
  useEffect(() => {
    void loadLists();
    if (asked.current || !args.length) return;
    const a = swarmArgs(args);
    if (a.mode === "bad") {
      setNote({ text: a.error, cls: "err" });
    } else if (a.mode === "run") {
      asked.current = true;
      void stream("/api/ai/swarm", { preset: a.preset, subject: a.subject, model: state.current.ai.model, provider: state.current.ai.provider });
    } else if (a.mode === "replay") {
      asked.current = true;
      void stream(`/api/ai/runs/${a.runId}/replay`, undefined);
    }
    replaceView(panelId, (v) => ({ ...v, args: [] }));
  }, [args, panelId, stream, loadLists]);

  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [run]);

  const saveThesis = useCallback(async () => {
    const r = state.current.run;
    const symbol = r ? subjectSymbol(r.subject) : null;
    if (!r?.final?.answer || !r.runId) return setNote({ text: "NOTHING TO SAVE YET: WAIT FOR THE CHAIR'S ANSWER", cls: "warn" });
    if (!symbol) return setNote({ text: "THE SUBJECT IS NOT A TICKER: USE THESIS ADD <SYMBOL> <TEXT>", cls: "warn" });
    const text = `SWARM ${r.preset} (MODEL OUTPUT, RUN ${r.runId}): ${r.final.answer}`.slice(0, 2000);
    try {
      const res = await fetch("/api/theses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, text, run_ids: [r.runId] }) });
      const j = await res.json().catch(() => null);
      setNote(res.ok ? { text: `THESIS ${j.thesis.id} SAVED FOR ${symbol}, LINKED TO RUN ${r.runId}: THESIS ${symbol}`, cls: "up" } : { text: j?.error ?? `HTTP ${res.status}`, cls: "err" });
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
    }
  }, []);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey || e.key === "Shift") return false;
        if (e.key === "Escape" && abort.current) {
          abort.current.abort();
          return true;
        }
        if ((e.key === "t" || e.key === "T") && !abort.current) {
          void saveThesis();
          return true;
        }
        if ((e.key === "x" || e.key === "X") && !abort.current) {
          setRun(null);
          setNote(null);
          return true;
        }
        return false;
      }),
    [panelId, saveThesis],
  );

  const running = run?.status === "running";
  return (
    <div className="fn" data-testid="swarm-panel">
      <div className="line">
        <span className="acc">SWARM</span> {run?.title ? `${run.title} · ${run.subject}` : "MULTI-AGENT DESKS"}
        <span className="dim"> · {run?.model || ai.model} · MODEL OUTPUT, NOT DATA · ESC CANCEL · T SAVE AS THESIS · X CLEAR</span>
      </div>
      {note && (
        <div className={note.cls} data-testid="swarm-note">
          {note.text}
        </div>
      )}
      <div className="ai-log" ref={log}>
        {!run && (
          <div data-testid="swarm-list">
            {(presets ?? []).map((p) => (
              <div key={p.code} data-testid="swarm-preset">
                <span className="acc">SWARM {p.code}</span> <span className="dim">{p.note} · ROLES {p.roles.map((r) => r.id).join(" > ")}</span>
              </div>
            ))}
            {stored.length > 0 && <div className="dim">STORED RUNS (SWARM REPLAY &lt;id&gt; SHOWS ONE AGAIN, NO MODEL CALL):</div>}
            {stored.map((s) => (
              <div key={s.id} data-testid="swarm-stored">
                {s.id} <span className="dim">· {new Date(s.created_at * 1000).toISOString().slice(0, 16).replace("T", " ")}Z · {s.title}</span>
              </div>
            ))}
          </div>
        )}
        {run?.replayOf && (
          <div className="warn" data-testid="swarm-replay">
            REPLAY OF STORED RUN {run.replayOf.runId} FROM {new Date(run.replayOf.createdAt * 1000).toISOString().slice(0, 16).replace("T", " ")}Z: NO MODEL WAS CALLED NOW
          </div>
        )}
        {run?.fixtures && <div className="warn">RECORDED MODEL REPLIES, NOT LIVE</div>}
        {run?.roles.map((r) => (
          <RoleView key={r.id} r={r} />
        ))}
        {run?.final && run.final.answer && (
          <div className="ai-turn" data-testid="swarm-final">
            <div className="acc">DESK ANSWER</div>
            <div className="ai-answer" data-testid="swarm-answer">
              {citeSegments(run.final.answer.replace(/\*\*/g, "")).map((s, i) => ("cite" in s ? <span key={i} className="acc">[{s.cite}]</span> : <span key={i}>{s.text}</span>))}
            </div>
            {run.final.failed.length > 0 && <div className="warn">ROLES THAT FAILED: {run.final.failed.join(", ")}</div>}
            {run.final.label && <div className="warn">{run.final.label}: NO ANALYST USED TOOL DATA</div>}
            {run.final.unsourced.length > 0 && (
              <div className="warn" data-testid="swarm-unsourced">
                UNSOURCED NUMBERS (NOT IN ANY ANALYST NOTE): {run.final.unsourced.join(" ")}
              </div>
            )}
            <div className="dim" data-testid="swarm-footer">
              AI · {run.model} · {run.started.slice(11, 19)}Z · MODEL OUTPUT, NOT DATA · US${run.cost.toFixed(4)}
              {run.runId ? ` · STORED RUN ${run.runId}` : ""}
            </div>
          </div>
        )}
        {run?.final && !run.final.answer && run.final.label === "INCOMPLETE" && <div className="warn">INCOMPLETE: THE SWARM WAS CANCELLED OR THE STREAM ENDED EARLY</div>}
        {run?.error && (
          <div className={run.error.kind === "key_required" ? "warn" : "err"} data-testid="swarm-error">
            {run.error.text}
          </div>
        )}
        {running && <div className="dim">RUNNING...</div>}
      </div>
    </div>
  );
}
