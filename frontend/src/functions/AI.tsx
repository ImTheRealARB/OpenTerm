/**
 * AI (Phase 16): research chat over OpenTerm's own data. The backend agent answers from tools (quotes, history, filings, quant jobs...) and this
 * panel shows every tool call with its source and age, the answer with its [T1] citations, and the verdict: UNGROUNDED when no tool returned
 * data, UNSOURCED NUMBERS for figures no tool returned. AI output is model output, not data. Keys never reach this code: the backend holds them.
 * Keys: I / Enter type a question, Enter sends, Esc cancels a running answer (or leaves the input), X clears the chat.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { registerPanelKeys } from "../keys/panelKeys";
import { gauges } from "../perf/metrics";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { replaceView } from "../state/workspace";
import { citeSegments, newTurn, parseSse, reduceTurn, turnLine, type AiEvent, type Turn } from "./aiStream";
import type { FunctionProps } from "./registry";

const MAX_TURNS = 30;

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
  const state = useRef({ turns, ai });
  state.current = { turns, ai };
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
    async (question: string) => {
      const { turns: cur, ai: cfg } = state.current;
      if (!question.trim() || cur.some((t) => t.status === "running")) return;
      const history = cur.filter((t) => t.status === "done" && t.answer).flatMap((t) => [{ role: "user", content: t.question }, { role: "assistant", content: t.answer }]);
      const idx = cur.length;
      setTurns((ts) => [...ts, newTurn(question)].slice(-MAX_TURNS));
      const apply = (e: AiEvent) => setTurns((ts) => ts.map((t, i) => (i === Math.min(idx, ts.length - 1) ? reduceTurn(t, e) : t)));
      const ac = new AbortController();
      abort.current = ac;
      const t0 = performance.now();
      let sawEvent = false;
      let sawToken = false;
      try {
        const res = await fetch("/api/ai/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, history, model: cfg.model, provider: cfg.provider }),
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
  const asked = useRef(false);
  useEffect(() => {
    void refreshSpend();
    if (asked.current || !args.length) return;
    asked.current = true;
    void send(args.join(" "));
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
          {spend ? ` · US$${spend.today.toFixed(2)} OF US$${spend.cap.toFixed(2)} TODAY` : ""} · MODEL OUTPUT, NOT DATA · I ASK · ESC CANCEL · X CLEAR
        </span>
      </div>
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
            e.stopPropagation();
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
