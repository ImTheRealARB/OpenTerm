/**
 * AUDIT (Phase 16): the hash-chained ledger of AI, SWARM, AI AUTO and BT runs. Each entry holds a manifest (prompt hash, tool registry hash, skill hashes,
 * app version, model) and metadata (question and answer hashes, tool calls with argument hashes, cost, grounding verdict); no prompt or answer text.
 * The chain is verified when the panel opens: changing or removing an entry breaks it from that entry on. Removing the newest entries cannot be seen
 * from the table, so note the HEAD hash. Keys: R verifies again, Up/Down (or J/K) select an entry to see its manifest and tool calls.
 * With `ai.storeText` on (SETTINGS), the redacted question and answer are kept locally in a side table outside the hash chain: entries that have
 * text show `T`; V reads it (on demand, read-only); P purges the selected entry's text and X all stored text (press twice to confirm).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { registerPanelKeys } from "../keys/panelKeys";
import { aiApi } from "../net/aiApi";
import { purgeMessage, purgeStep, type PurgeAsk } from "./auditText";
import type { FunctionProps } from "./registry";

interface Entry {
  seq: number;
  at: number;
  kind: string;
  ref: string;
  model: string;
  manifest: Record<string, unknown> & { prompt_sha?: string; tools_sha?: string; tools?: string[]; app?: string; skills?: Record<string, string> };
  meta: Record<string, unknown> & { cost?: number | null; grounded?: boolean | null; unsourced?: number; tool_calls?: { id: string; name: string; ok: boolean | null; source: string | null; role?: string | null }[] };
  prev_hash: string;
  hash: string;
  has_text?: boolean;
}
interface StoredText {
  seq: number;
  question: string;
  answer: string;
  stored_at: number;
}
interface Verdict {
  ok: boolean;
  count: number;
  head: string;
  broken_at: number | null;
  reason: string | null;
}

const when = (t: number) => new Date(t * 1000).toISOString().slice(0, 19).replace("T", " ") + "Z";

export default function AUDIT({ panelId }: FunctionProps) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [sel, setSel] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [ask, setAsk] = useState<PurgeAsk>(null);
  const [text, setText] = useState<StoredText | null>(null);
  const [note, setNote] = useState<{ text: string; cls: string } | null>(null);
  const count = useRef(0);
  count.current = entries.length;
  const live = useRef({ entries, sel, ask });
  live.current = { entries, sel, ask };

  const load = useCallback(async (): Promise<boolean | null> => {
    try {
      const [l, v] = await Promise.all([aiApi.ledger<{ entries: Entry[] }>(), aiApi.ledgerVerify<Verdict>()]);
      if (!l.ok || !v.ok) {
        setErr(`HTTP ${l.ok ? v.status : l.status}`);
        return null;
      }
      setEntries(l.json!.entries);
      setVerdict(v.json as Verdict);
      setErr(null);
      return (v.json as Verdict).ok;
    } catch {
      setErr("BACKEND DOWN");
      return null;
    }
  }, []);

  const view = useCallback(async (seq: number) => {
    try {
      const r = await aiApi.ledgerText<StoredText & { error?: string }>(seq);
      if (r.ok && r.json) {
        setText(r.json);
        setNote(null);
      } else {
        setText(null);
        setNote({ text: r.status === 404 ? `NO STORED TEXT FOR ENTRY ${seq} (SETTINGS AI STORETEXT WAS OFF, OR IT WAS PURGED)` : `HTTP ${r.status}`, cls: "warn" });
      }
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
    }
  }, []);

  const purge = useCallback(
    async (scope: "ONE" | "ALL", seq: number) => {
      try {
        const r = await aiApi.purgeLedgerText<{ purged: number }>(scope === "ALL" ? null : seq);
        if (!r.ok || !r.json) return setNote({ text: `PURGE FAILED: HTTP ${r.status}`, cls: "err" });
        setText(null);
        const ok = await load();
        setNote({ text: purgeMessage(scope, seq, r.json.purged, ok), cls: ok === false ? "err" : "up" });
      } catch {
        setNote({ text: "BACKEND DOWN", cls: "err" });
      }
    },
    [load],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const k = e.key.toLowerCase();
        const { entries: es, sel: i, ask: a } = live.current;
        const row = es[Math.min(i, es.length - 1)];
        if (k === "p" || k === "x") {
          const step = purgeStep(a, k);
          setAsk(step.ask);
          if (step.run && (step.run === "ALL" || row)) void purge(step.run, row?.seq ?? 0);
          return true;
        }
        if (a) setAsk(null);
        if (k === "r") void load();
        else if (k === "v") {
          if (row) void view(row.seq);
        } else if (k === "arrowdown" || k === "j" || k === "arrowup" || k === "k") {
          setText(null);
          setNote(null);
          if (k === "arrowdown" || k === "j") setSel((s) => Math.min(count.current - 1, s + 1));
          else setSel((s) => Math.max(0, s - 1));
        } else return false;
        return true;
      }),
    [panelId, load, view, purge],
  );

  const cur = entries[Math.min(sel, entries.length - 1)];
  const cost = (e: Entry) => (typeof e.meta.cost === "number" ? `US$${e.meta.cost.toFixed(4)}` : "-");
  return (
    <div className="fn" data-testid="audit-panel">
      <div className="line">
        <span className="acc">AUDIT</span> <span className="dim">AI, SWARM, AI AUTO AND BT RUNS · HASHES AND METADATA; TEXT ONLY IF SETTINGS AI STORETEXT IS ON (T = STORED, LOCAL ONLY) · R VERIFY · UP/DOWN SELECT · V VIEW TEXT · P PURGE ENTRY TEXT · X PURGE ALL TEXT</span>
      </div>
      {err && <div className="err">{err}</div>}
      {verdict && (
        <div className={verdict.ok ? "up" : "err"} data-testid="audit-verdict">
          {verdict.ok
            ? `CHAIN OK · ${verdict.count} ENTRIES · HEAD ${verdict.head.slice(0, 16)}`
            : `CHAIN BROKEN AT ENTRY ${verdict.broken_at}: ${verdict.reason}`}
        </div>
      )}
      {ask && (
        <div className="err" data-testid="audit-confirm">
          {ask === "ALL" ? "REMOVE ALL STORED AI TEXT? PRESS X AGAIN (ANY OTHER KEY CANCELS). THE HASH CHAIN IS NOT AFFECTED." : `REMOVE THE STORED TEXT OF ENTRY ${cur?.seq ?? "-"}? PRESS P AGAIN (ANY OTHER KEY CANCELS). THE HASH CHAIN IS NOT AFFECTED.`}
        </div>
      )}
      {note && <div className={note.cls} data-testid="audit-note">{note.text}</div>}
      {verdict?.ok && verdict.count === 0 && <div className="dim">NO RUNS RECORDED YET: ASK THE AI, RUN A SWARM, OR RUN A BACKTEST</div>}
      <div className="ai-log">
        {entries.map((e, i) => (
          <div key={e.seq} className={i === Math.min(sel, entries.length - 1) ? "acc" : ""} data-testid="audit-row">
            {i === Math.min(sel, entries.length - 1) ? "> " : "  "}
            {String(e.seq).padStart(4)} {when(e.at)} {e.kind.toUpperCase().padEnd(8)} {(e.ref || "-").padEnd(12)} {e.model.slice(0, 28).padEnd(28)} {cost(e).padEnd(10)} {e.hash.slice(0, 10)} {e.has_text ? "T" : " "}
          </div>
        ))}
        {cur && (
          <div className="ai-turn" data-testid="audit-detail">
            <div className="dim">
              HASH {cur.hash} · PREVIOUS {cur.prev_hash.slice(0, 16)}
            </div>
            <div>
              PROMPT {cur.manifest.prompt_sha?.slice(0, 16) ?? "-"} · TOOLS {cur.manifest.tools_sha?.slice(0, 16) ?? "-"} ({cur.manifest.tools?.length ?? 0}) · APP {cur.manifest.app ?? "-"}
              {cur.meta.grounded === false ? " · UNGROUNDED" : ""}
              {cur.meta.unsourced ? ` · ${cur.meta.unsourced} UNSOURCED NUMBERS` : ""}
            </div>
            {text && text.seq === cur.seq && (
              <div data-testid="audit-text">
                <div className="dim">STORED TEXT (REDACTED, LOCAL ONLY) · {when(text.stored_at)}</div>
                <div>QUESTION: {text.question}</div>
                <div style={{ whiteSpace: "pre-wrap" }}>ANSWER: {text.answer}</div>
              </div>
            )}
            {(cur.meta.tool_calls ?? []).map((t, i) => (
              <div key={i} className={t.ok === false ? "warn" : "dim"}>
                [{t.id}] {t.role ? `${t.role} ` : ""}
                {t.name} · {t.source ?? "-"} · {t.ok === null ? "NO RESULT" : t.ok ? "OK" : "FAILED"}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
