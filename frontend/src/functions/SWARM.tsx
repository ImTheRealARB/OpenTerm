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
import { commandFor, coverageLabel, subjectSymbol, swarmArgs, type PresetInfo, type PresetsResponse } from "./swarmArgs";
import { estimateLine, newSwarm, reduceSwarm, type RoleState, type SwarmEvent, type SwarmState } from "./swarmStream";
import { watchPanelGone } from "./panelGoneWatch";
import { usePanelMemory } from "./usePanelMemory";

interface StoredRun {
  id: string;
  kind: string;
  title: string;
  symbol: string | null;
  created_at: number;
}

const STATE_LABEL: Record<RoleState["state"], string> = { waiting: "WAITING", running: "RUNNING", done: "DONE", failed: "FAILED" };
/** FULL is plain, PARTIAL is a warning, UNAVAILABLE is an error: colour only carries that meaning. */
const COVERAGE_CLASS = { FULL: "dim", PARTIAL: "warn", UNAVAILABLE: "err" } as const;

/** What a desk needs typed after its name, e.g. `TARGET=<value>` (required) or `[HORIZON=<value>]` (optional). */
const variableUsage = (p: PresetInfo) => p.variables.map((v) => (v.required ? `${v.name.toUpperCase()}=<value>` : `[${v.name.toUpperCase()}=<value>]`)).join(" ");

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
  // The run lives in per-panel memory, not useState: a typed command (`SWARM ...`) remounts the panel.
  const [run, setRun] = usePanelMemory<SwarmState | null>("SWARM", panelId, "run", null);
  const [desks, setDesks] = useState<PresetsResponse | null>(null);
  const [stored, setStored] = useState<StoredRun[]>([]);
  const [note, setNote] = useState<{ text: string; cls: string } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const lastRun = useRef<{ preset: string; subject: string; variables: Record<string, string> } | null>(null); // for the "run anyway" command
  const state = useRef({ run, ai });
  state.current = { run, ai };
  const log = useRef<HTMLDivElement>(null);

  /** Loads the desks (every one the backend knows, including the user's own files) and the stored runs. Returns the desks for argument parsing. */
  const loadLists = useCallback(async (): Promise<PresetInfo[]> => {
    try {
      const [p, r] = await Promise.all([fetch("/api/ai/swarm/presets"), fetch("/api/ai/runs?kind=swarm")]);
      let list: PresetInfo[] = [];
      if (p.ok) {
        const body = (await p.json()) as PresetsResponse;
        setDesks(body);
        list = body.presets;
      }
      if (r.ok) setStored(((await r.json()) as { runs: StoredRun[] }).runs);
      return list;
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
      return [];
    }
  }, []);

  const stream = useCallback(async (url: string, body: unknown) => {
    const ac = new AbortController();
    abort.current = ac;
    let cur = newSwarm();
    // `gone` = the panel closed or moved on to another view: this run's late writes go inert, so
    // they cannot overwrite the run the panel shows now.
    let gone = false;
    const incomplete = (): SwarmState => ({ ...cur, status: "done", final: { answer: "", unsourced: [], grounded: false, label: "INCOMPLETE", failed: [] } });
    // Stop the (paid) run if this panel is closed or its view is replaced (a new command, a history
    // step). A maximize remount keeps the same view, so it does not count.
    const unwatch = watchPanelGone(panelId, () => {
      setRun(incomplete());
      gone = true;
      ac.abort();
    });
    setRun(cur);
    const apply = (e: SwarmEvent) => {
      if (gone) return;
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
      if (cur.status === "running" && !gone) setRun(incomplete());
    } catch (e) {
      if (gone) {
        /* already marked INCOMPLETE when the panel moved on */
      } else if ((e as Error).name === "AbortError") setRun(incomplete());
      else apply({ type: "error", kind: "network", text: "BACKEND DOWN" });
    } finally {
      unwatch();
      abort.current = null;
      void loadLists();
    }
  }, [loadLists, panelId, setRun]);

  // The args array this instance already acted on. A boolean "asked once" flag ignored every later command typed into the
  // same instance, which happens once the panel's history reaches its 50-entry cap (pos stops changing, so no remount).
  // Args are cleared right after they are read, so a new non-empty array is always a new command (audit F-1).
  const consumed = useRef<readonly string[] | null>(null);
  useEffect(() => {
    const loaded = loadLists();
    if (consumed.current === args || !args.length) return;
    consumed.current = args;
    // The desks must be known before the arguments are read: `SWARM MYDESK TARGET=AAPL` only means something once we know MYDESK has a TARGET.
    void loaded.then((list) => {
      const a = swarmArgs(args, list);
      if (a.mode === "bad") {
        setNote({ text: a.error, cls: "err" });
      } else if (a.mode === "run") {
        lastRun.current = { preset: a.preset, subject: a.subject, variables: a.variables };
        const body: Record<string, unknown> = { preset: a.preset, subject: a.subject, model: state.current.ai.model, provider: state.current.ai.provider };
        if (Object.keys(a.variables).length) body.variables = a.variables;
        if (a.force) body.force = true; // past the daily spend-cap check (the cap itself still stops a run that reaches it)
        void stream("/api/ai/swarm", body);
      } else if (a.mode === "replay") {
        void stream(`/api/ai/runs/${a.runId}/replay`, undefined);
      }
    });
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
            {(desks?.presets ?? []).map((p) => (
              <div key={p.code} data-testid="swarm-preset" data-coverage={p.coverage}>
                <span className="acc">
                  SWARM {p.code} {variableUsage(p)}
                </span>{" "}
                <span className={COVERAGE_CLASS[p.coverage]} data-testid="swarm-coverage">
                  {coverageLabel(p)}
                </span>{" "}
                <span className="dim">
                  · {p.title}. {p.note} · ROLES {p.roles.map((r) => r.id).join(" > ")}
                  {p.source.startsWith("user:") ? " · YOUR FILE" : ""}
                </span>
                {p.variables.map((v) => (
                  <div key={v.name} className="dim" data-testid="swarm-variable">
                    {"  "}
                    {v.name.toUpperCase()} {v.required ? "(REQUIRED)" : "(OPTIONAL)"} {v.description}
                  </div>
                ))}
                <div className="dim" data-testid="swarm-list-estimate">
                  {"  "}
                  {estimateLine(p.estimate)}
                </div>
              </div>
            ))}
            {desks && Object.keys(desks.errors).length > 0 && <div className="warn">DESK FILES THAT FAILED TO LOAD (NOT RUN):</div>}
            {Object.entries(desks?.errors ?? {}).map(([file, why]) => (
              <div key={file} className="warn" data-testid="swarm-load-error">
                {file}: {why}
              </div>
            ))}
            {desks && (
              <div className="dim" data-testid="swarm-spend">
                TODAY'S AI SPEND US${desks.spend.today.toFixed(2)} OF US${desks.spend.cap.toFixed(2)} CAP · A RUN WHOSE WORST CASE IS OVER WHAT IS LEFT NEEDS --force
              </div>
            )}
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
        {run && run.preset && (
          <div data-testid="swarm-run-info">
            <div className={COVERAGE_CLASS[run.coverage]} data-testid="swarm-run-coverage">
              COVERAGE {coverageLabel(run)}
            </div>
            {Object.keys(run.variables).length > 0 && (
              <div className="dim" data-testid="swarm-run-variables">
                {Object.entries(run.variables)
                  .map(([k, v]) => `${k.toUpperCase()}=${v}`)
                  .join(" · ")}
              </div>
            )}
            {run.estimate && (
              <div className="dim" data-testid="swarm-estimate">
                {estimateLine(run.estimate)}
              </div>
            )}
          </div>
        )}
        {run?.roles.map((r) => (
          <RoleView key={r.id} r={r} />
        ))}
        {run?.final && run.final.answer && (
          <div className="ai-turn" data-testid="swarm-final">
            <div className="acc">DESK ANSWER</div>
            <div className="ai-answer" data-testid="swarm-answer">
              {citeSegments(run.final.answer.replace(/\*\*/g, "")).map((s, i) => ("cite" in s ? <span key={i} className="acc">[{s.cite}]</span> : <span key={i}>{s.text}</span>))}
            </div>
            {run.capped && (
              <div className="warn" data-testid="swarm-capped">
                THE RUN HIT ITS OUTPUT CAP AND STOPPED: THE ANSWER ABOVE MAY BE INCOMPLETE
              </div>
            )}
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
        {run?.error?.kind === "spend_cap" && lastRun.current && (
          <div className="acc" data-testid="swarm-force">
            TO RUN ANYWAY: {commandFor(lastRun.current, "--force")}
          </div>
        )}
        {running && <div className="dim">RUNNING...</div>}
      </div>
    </div>
  );
}
