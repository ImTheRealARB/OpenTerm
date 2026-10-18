/**
 * AI (Phase 16): research chat over OpenTerm's own data. The backend agent answers from tools (quotes, history, filings, quant jobs...) and this
 * panel shows every tool call with its source and age, the answer with its [T1] citations, and the verdict: UNGROUNDED when no tool returned
 * data, UNSOURCED NUMBERS for figures no tool returned. AI output is model output, not data. Keys never reach this code: the backend holds them.
 * `AI BT <idea>` drafts a backtest rule (validated by the BT parser, shown, never run by the AI: B puts the BT command on the command line).
 * `AI CHART` sends the chart of the newest GP panel to a vision model. Both answers are labelled model output.
 * `AI DOC FILING <SYM> [FORM]` or U (upload a TXT, CSV, HTML, DOCX, XLSX or PDF) loads one document; questions then use only its text, with chunk
 * citations (`AI DOC OFF` goes back to market data). Keys: I / Enter type a question, Enter sends, Esc cancels a running answer (or leaves the input), X clears the chat.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { latestChartShot } from "../chart/shot";
import { prefillCommand } from "../components/CommandLine";
import { registerPanelKeys } from "../keys/panelKeys";
import { gauges } from "../perf/metrics";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { replaceView } from "../state/workspace";
import { aiArgs } from "./aiArgs";
import { citeSegments, newTurn, parseSse, reduceTurn, turnLine, type AiEvent, type Turn } from "./aiStream";
import type { FunctionProps } from "./registry";

const MAX_TURNS = 30;
interface DocCard {
  id: string;
  name: string;
  kind: string;
  chunks: number;
  chars: number;
  preview: string;
}

function Answer({ text, running }: { text: string; running: boolean }) {
  return (
    <div className="ai-answer" data-testid="ai-answer">
      {citeSegments(text.replace(/\*\*/g, "")).map((s, i) => ("cite" in s ? <span key={i} className="acc">[{s.cite}]</span> : <span key={i}>{s.text}</span>))}
      {running && <span className="dim">{text ? " ▌" : "▌"}</span>}
    </div>
  );
}

function TurnView({ t }: { t: Turn }) {
  return (
    <div className="ai-turn" data-testid="ai-turn">
      <div className="acc">&gt; {t.question}</div>
      {t.tools.map((r) => (
        <div key={r.id} className={r.state === "failed" ? "warn" : "dim"} data-testid="ai-tool">
          [{r.id}] {r.name} {JSON.stringify(r.args)} · {r.source ?? "-"}
          {r.age_s != null ? ` · ${r.age_s < 10 ? r.age_s.toFixed(1) : Math.round(r.age_s)}s` : ""}
          {r.stale ? " · STALE" : ""} · {r.state === "running" ? "RUNNING" : r.state.toUpperCase()}
          {r.state === "failed" && r.summary ? ` · ${r.summary}` : ""}
        </div>
      ))}
      {t.notices.map((n, i) => (
        <div key={i} className="warn">
          {n}
        </div>
      ))}
      {(t.answer || t.status === "running") && <Answer text={t.answer} running={t.status === "running"} />}
      {t.status === "done" && (
        <div className="dim" data-testid="ai-footer">
          {turnLine(t)}
        </div>
      )}
      {t.fixtures && <div className="warn">RECORDED MODEL REPLY, NOT LIVE</div>}
      {t.status === "done" && t.label && (
        <div className="warn" data-testid="ai-label">
          {t.label}: NO TOOL RETURNED DATA FOR THIS ANSWER, IT COMES FROM THE MODEL
        </div>
      )}
      {t.draft && (
        <div data-testid="ai-draft">
          <div className="dim">{t.draft.rationale}</div>
          <div>
            <span className="dim">RULE </span>
            <span className="acc">{t.draft.rule}</span>
            <span className="dim"> · {t.draft.symbols.join(",")} · {t.draft.interval} · {t.draft.range}</span>
          </div>
          <div>
            <span className="dim">COMMAND </span>
            {t.draft.command}
          </div>
          <div className="warn">{t.draft.note}</div>
          <div className="dim">B PUTS THE COMMAND ON THE COMMAND LINE, THEN ENTER RUNS IT IN BT</div>
        </div>
      )}
      {t.draftError && (
        <div className="warn" data-testid="ai-draft-error">
          {t.draftError}
        </div>
      )}
      {t.unsourced.length > 0 && (
        <div className="warn" data-testid="ai-unsourced">
          UNSOURCED NUMBERS (NO TOOL RETURNED THEM): {t.unsourced.join(" ")}
        </div>
      )}
      {t.error && (
        <div className={t.error.kind === "key_required" ? "warn" : "err"} data-testid="ai-error">
          {t.error.text}
        </div>
      )}
    </div>
  );
}

export default function AI({ panelId, args }: FunctionProps) {
  const ai = useStore(settingsStore, (s) => s.ai);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [spend, setSpend] = useState<{ today: number; cap: number } | null>(null);
  const [doc, setDoc] = useState<DocCard | null>(null);
  const [note, setNote] = useState<{ text: string; cls: string } | null>(null);
  const state = useRef({ turns, ai, doc });
  state.current = { turns, ai, doc };
  const picker = useRef<HTMLInputElement>(null);
  const running = turns.some((t) => t.status === "running");
  const abort = useRef<AbortController | null>(null);
  const box = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);

  const refreshSpend = useCallback(async () => {
    try {
      const r = await fetch("/api/llm/health");
      const j = await r.json();
      if (j?.spend) setSpend(j.spend);
    } catch {
      /* the header just keeps its last value */
    }
  }, []);

  const send = useCallback(
    async (question: string, mode: "ask" | "bt" | "chart" = "ask") => {
      const { turns: cur, ai: cfg, doc: curDoc } = state.current;
      if ((mode !== "chart" && !question.trim()) || cur.some((t) => t.status === "running")) return;
      const label = mode === "bt" ? "AI BT" : mode === "chart" ? "AI CHART" : "";
      const shown = label ? `${label} ${question}`.trim() : question;
      const shot = mode === "chart" ? latestChartShot() : null;
      const image = shot?.shot() ?? null;
      if (mode === "chart" && !image) {
        const t = reduceTurn(newTurn(shown), { type: "error", kind: "no_chart", text: "OPEN A CHART FIRST (GP <SYMBOL>), THEN AI CHART" });
        setTurns((ts) => [...ts, t].slice(-MAX_TURNS));
        return;
      }
      const history = mode !== "ask" ? [] : cur.filter((t) => t.status === "done" && t.answer).flatMap((t) => [{ role: "user", content: t.question }, { role: "assistant", content: t.answer }]);
      const idx = cur.length;
      setTurns((ts) => [...ts, newTurn(shown)].slice(-MAX_TURNS));
      const apply = (e: AiEvent) => setTurns((ts) => ts.map((t, i) => (i === Math.min(idx, ts.length - 1) ? reduceTurn(t, e) : t)));
      const ac = new AbortController();
      abort.current = ac;
      const t0 = performance.now();
      let sawEvent = false;
      let sawToken = false;
      try {
        const asking = mode === "ask" && curDoc;
        const url = mode === "bt" ? "/api/ai/bt" : mode === "chart" ? "/api/ai/chart" : asking ? "/api/ai/doc/ask" : "/api/ai/chat";
        const payload =
          mode === "bt"
            ? { idea: question, model: cfg.model, provider: cfg.provider }
            : mode === "chart"
              ? { image, symbol: shot!.symbol, range: shot!.range, model: cfg.visionModel, provider: cfg.provider }
              : { question, history, model: cfg.model, provider: cfg.provider, ...(asking ? { doc_id: curDoc.id } : {}) };
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: ac.signal,
        });
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
          const parsed = parseSse(buf);
          buf = parsed.rest;
          for (const e of parsed.events) {
            if (!sawEvent) {
              sawEvent = true;
              gauges.set("ai.first_event_ms", performance.now() - t0);
            }
            if (e.type === "token" && !sawToken) {
              sawToken = true;
              gauges.set("ai.first_token_ms", performance.now() - t0);
            }
            apply(e);
          }
        }
        // The stream ended without done or error (server stopped): do not leave the turn spinning.
        setTurns((ts) => ts.map((t, i) => (i === Math.min(idx, ts.length - 1) && t.status === "running" ? { ...t, status: "done", label: "INCOMPLETE" } : t)));
      } catch (e) {
        if ((e as Error).name === "AbortError") {
          setTurns((ts) => ts.map((t, i) => (i === Math.min(idx, ts.length - 1) ? { ...t, status: "done", label: "INCOMPLETE", notices: [...t.notices, "CANCELLED (ESC)"] } : t)));
        } else apply({ type: "error", kind: "network", text: "BACKEND DOWN" });
      } finally {
        abort.current = null;
        void refreshSpend();
      }
    },
    [refreshSpend],
  );

  const sendInput = useCallback(() => {
    const q = box.current?.value ?? "";
    if (!q.trim()) return;
    setInput("");
    void send(q);
  }, [send]);

  // `AI <question>` from the command line sends once, then the view goes back to a plain chat so a remount does not ask again.
  const loaded = (r: Response, j: { doc?: DocCard; error?: string; url?: string } | null) => {
    if (!r.ok || !j?.doc) {
      setNote({ text: j?.error ?? `HTTP ${r.status}`, cls: "err" });
      return;
    }
    setDoc(j.doc);
    setNote({ text: `DOCUMENT LOADED: ${j.doc.name} · ${j.doc.kind.toUpperCase()} · ${j.doc.chunks} CHUNKS · ${j.doc.chars.toLocaleString("en-US")} CHARACTERS · ASK ABOUT IT; ONLY ITS TEXT IS USED`, cls: "up" });
  };
  const loadFiling = async (symbol: string, form: string) => {
    setNote({ text: `FETCHING ${symbol} ${form} FROM SEC...`, cls: "dim" });
    try {
      const r = await fetch("/api/ai/doc/filing", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, form }) });
      loaded(r, await r.json().catch(() => null));
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
    }
  };
  const uploadFile = async (file: File) => {
    setNote({ text: `READING ${file.name}...`, cls: "dim" });
    try {
      const r = await fetch(`/api/ai/doc/upload?name=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
      loaded(r, await r.json().catch(() => null));
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
    }
  };

  const asked = useRef(false);
  useEffect(() => {
    void refreshSpend();
    if (asked.current || !args.length) return;
    const a = aiArgs(args);
    if (a.mode === "doc") {
      setNote({ text: "PRESS U TO PICK A FILE (TXT CSV HTML DOCX XLSX PDF), OR: AI DOC FILING <SYMBOL> [FORM]", cls: "dim" });
    } else if (a.mode === "docoff") {
      setDoc(null);
      setNote({ text: "DOCUMENT UNLOADED: QUESTIONS USE MARKET DATA TOOLS AGAIN", cls: "dim" });
    } else if (a.mode === "docfiling") {
      void loadFiling(a.symbol, a.form);
    } else if (a.mode === "bad") {
      setTurns([reduceTurn(newTurn("AI " + args.join(" ")), { type: "error", kind: "usage", text: a.error })]);
    } else if (a.mode !== "ask" || a.text) {
      asked.current = true;
      void send(a.text, a.mode);
    } else return;
    replaceView(panelId, (v) => ({ ...v, args: [] }));
  }, [args, panelId, send, refreshSpend]);

  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey || e.key === "Shift") return false;
        if (e.key === "Escape" && abort.current) {
          abort.current.abort();
          return true;
        }
        if (e.key === "u" || e.key === "U") {
          picker.current?.click();
          return true;
        }
        if (e.key === "b" || e.key === "B") {
          const d = [...state.current.turns].reverse().find((t) => t.draft)?.draft;
          if (!d) return false;
          prefillCommand(d.command);
          return true;
        }
        if (e.key === "i" || e.key === "I" || e.key === "Enter") {
          box.current?.focus();
          return true;
        }
        if ((e.key === "x" || e.key === "X") && !abort.current) {
          setTurns([]);
          return true;
        }
        return false;
      }),
    [panelId],
  );

  const lite = ai.model.endsWith(":free");
  return (
    <div className="fn" data-testid="ai-panel">
      <div className="line">
        <span className="acc">AI</span> {ai.model}
        <span className="dim">
          {" "}
          · {ai.provider.toUpperCase()}
          {spend ? ` · US$${spend.today.toFixed(2)} OF US$${spend.cap.toFixed(2)} TODAY` : ""} · MODEL OUTPUT, NOT DATA · I ASK · ESC CANCEL · X CLEAR · U DOC · AI BT IDEA · AI CHART
        </span>
      </div>
      {doc && (
        <div className="line" data-testid="ai-doc">
          <span className="acc">DOC</span> {doc.name} <span className="dim">· {doc.kind.toUpperCase()} · {doc.chunks} CHUNKS · AI DOC OFF UNLOADS</span>
        </div>
      )}
      {note && (
        <div className={note.cls} data-testid="ai-note">
          {note.text}
        </div>
      )}
      <input
        ref={picker}
        type="file"
        hidden
        data-testid="ai-file"
        accept=".txt,.md,.json,.csv,.htm,.html,.docx,.xlsx,.pdf"
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void uploadFile(f);
        }}
      />
      {lite && <div className="warn">LITE MODELS CALL TOOLS BADLY AND ANSWER FROM MEMORY: SETTINGS AI MODEL</div>}
      <div className="ai-log" ref={log}>
        {turns.length === 0 && (
          <div className="dim">
            ASK ABOUT QUOTES, FILINGS, NEWS, YOUR PORTFOLIO OR A BACKTEST. EVERY NUMBER COMES FROM A TOOL CALL SHOWN BELOW THE QUESTION; AN ANSWER WITH NO TOOL DATA SAYS UNGROUNDED.
          </div>
        )}
        {turns.map((t, i) => (
          <TurnView key={i} t={t} />
        ))}
      </div>
      <div className="ai-in">
        <span className="acc">&gt;</span>
        <input
          ref={box}
          className="ai-input"
          aria-label="AI question"
          spellCheck={false}
          autoComplete="off"
          placeholder={running ? "ANSWERING... ESC CANCELS" : "TYPE A QUESTION, ENTER SENDS"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (!e.ctrlKey && !e.altKey && !e.metaKey) e.stopPropagation(); // Ctrl+K, Alt+digits and friends still reach the global bindings
            if (e.key === "Enter") {
              e.preventDefault();
              sendInput();
            } else if (e.key === "Escape") {
              e.preventDefault();
              if (abort.current) abort.current.abort();
              else box.current?.blur();
            }
          }}
        />
      </div>
    </div>
  );
}
