/**
 * BT EDIT / BT LOAD (Phase 12 step 4B): the Python strategy editor. `BT EDIT` lists saved strategies (Enter opens one, D
 * twice deletes); `BT EDIT <NAME>` opens or creates one. The box holds a `SignalEngine` (spec section 1) for a Python
 * strategy, or the rule text for a saved rule. Ctrl+S saves (the server checks the code against the sandbox allowlist and
 * says why it refuses), Ctrl+Enter saves and runs it with the RUN line below the box (`SYMBOLS [1D|1W] [RANGE] [OPTIONS]`),
 * which opens the result as `BT <SYMBOLS> @<NAME> ...`. Tab inserts four spaces; Esc leaves the box.
 */
import { useEffect, useRef, useState } from "react";
import { isBtRun, parseBtArgs } from "../bt/ruleParse";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, btApi, type BtStrategy, type BtStrategyCard } from "../net/api";
import { replaceView } from "../state/workspace";
import { navKey, useLatest } from "./quoteRows";

const errText = (e: unknown) => {
  const a = e as ApiError;
  return `${a.message ?? String(e)}${a.detail ? `: ${a.detail}` : ""}`;
};
export const NAME_RE = /^[a-z0-9_-]{1,40}$/;

export const TEMPLATE = `import numpy as np
import pandas as pd


class SignalEngine:
    def generate(self, data_map):
        """data_map: symbol -> DataFrame (open, high, low, close, volume). Return symbol -> Series of target
        weights in [-1, 1] on the same index (NaN counts as 0). Orders fill at the next bar's open."""
        out = {}
        for sym, df in data_map.items():
            fast = df["close"].rolling(20).mean()
            slow = df["close"].rolling(50).mean()
            out[sym] = pd.Series(np.where(fast > slow, 1.0, 0.0), index=df.index)
        return out
`;

const COLS: Column<BtStrategyCard>[] = [
  { title: "NAME", width: 24, text: (s) => s.name, color: () => "acc" },
  { title: "KIND", width: 8, text: (s) => (s.kind === "rule" ? "RULE" : "PYTHON") },
  { title: "SAVED", width: 12, align: "right", text: (s) => `${fmtAge(Date.now() / 1000 - s.updated_at)} AGO`, color: () => "dim" },
];

export default function BtEditor({ panelId, name }: { panelId: number; name?: string }) {
  return name ? <Editor panelId={panelId} name={name.toLowerCase()} /> : <Saved panelId={panelId} />;
}

function Saved({ panelId }: { panelId: number }) {
  const [rows, setRows] = useState<BtStrategyCard[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);
  const latest = useLatest({ rows, confirm });
  const reload = () =>
    btApi
      .strategies()
      .then((r) => setRows(r.strategies))
      .catch((e) => setMsg(`ERR: ${errText(e)}`));
  useEffect(() => {
    void reload();
  }, []);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey || e.key === "Shift") return false;
        const { rows: r, confirm: c } = latest.current;
        if (!r) return false;
        if (navKey(e, grid.current, r.length)) return true;
        const row = r[grid.current?.selected() ?? 0];
        if (!row) return false;
        if (e.key === "Enter") {
          replaceView(panelId, (v) => ({ ...v, args: ["EDIT", row.name] }));
          return true;
        }
        if (e.key.toLowerCase() === "d") {
          if (c === row.name) {
            setConfirm(null);
            btApi
              .deleteStrategy(row.name)
              .then(() => {
                setMsg(`DELETED ${row.name}`);
                return reload();
              })
              .catch((err) => setMsg(`ERR: ${errText(err)}`));
          } else setConfirm(row.name);
          return true;
        }
        return false;
      }),
    // everything is read through `latest`
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">BT STRATEGIES</span>{" "}
        <span className="dim">
          {rows ? `${rows.length} SAVED` : "LOADING…"} · ENTER EDIT · D TWICE DELETE · BT EDIT &lt;NAME&gt; CREATES ONE · BT SAVE &lt;NAME&gt; &lt;RULE&gt; SAVES A RULE · RUN: BT &lt;SYMBOLS&gt; @&lt;NAME&gt; 1D 5Y
        </span>
        {confirm && <span className="err"> · DELETE {confirm}? PRESS D AGAIN</span>}
      </div>
      {msg && <div className="dim">{msg}</div>}
      {rows && rows.length > 0 && <Grid ref={grid} columns={COLS} rows={rows} />}
      {rows && !rows.length && <div className="dim">NO SAVED STRATEGIES YET</div>}
    </div>
  );
}

function Editor({ panelId, name }: { panelId: number; name: string }) {
  const [saved, setSaved] = useState<BtStrategy | null | "new">(null);
  const [text, setText] = useState("");
  const [runLine, setRunLine] = useState("AAPL 1D 5Y");
  const [msg, setMsg] = useState<{ cls: string; text: string } | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const latest = useLatest({ text, runLine, saved });
  const valid = NAME_RE.test(name);

  useEffect(() => {
    if (!valid) return;
    let live = true;
    btApi
      .strategy(name)
      .then((s) => {
        if (!live) return;
        setSaved(s);
        setText(s.code);
      })
      .catch((e: ApiError) => {
        if (!live) return;
        if (e.status === 404) {
          setSaved("new");
          setText(TEMPLATE);
        } else setMsg({ cls: "err", text: `ERR: ${errText(e)}` });
      });
    return () => {
      live = false;
    };
  }, [name, valid]);

  useEffect(() => {
    if (saved === null) return;
    box.current?.focus();
    const t = setTimeout(() => box.current?.focus(), 80); // the command line hands focus back after Esc
    return () => clearTimeout(t);
  }, [saved]);

  const isRule = saved !== null && saved !== "new" && saved.kind === "rule";
  const save = async (): Promise<boolean> => {
    const { text: body } = latest.current;
    setMsg({ cls: "dim", text: "SAVING…" });
    try {
      const r = await btApi.putStrategy(name, isRule ? { rule: body.trim() } : { code: body });
      setSaved({ name: r.name, kind: r.kind, code: isRule ? body.trim() : body, updated_at: r.updated_at });
      setMsg({ cls: "dim", text: `SAVED ${name} (${r.kind === "rule" ? "RULE" : "PYTHON"}) · RUN IT: BT <SYMBOLS> @${name} 1D 5Y OR CTRL+ENTER` });
      return true;
    } catch (e) {
      setMsg({ cls: "err", text: `NOT SAVED: ${errText(e)}` });
      return false;
    }
  };
  const run = async () => {
    const tokens = latest.current.runLine.trim().split(/\s+/).filter(Boolean);
    const args = [tokens[0] ?? "", `@${name}`, ...tokens.slice(1)];
    const p = parseBtArgs(args);
    if (!tokens.length || !p.ok || !isBtRun(p)) return setMsg({ cls: "err", text: `RUN LINE: ${p.ok ? "USAGE: SYMBOLS [1D|1W] [RANGE] [OPTIONS]" : p.error}` });
    if (await save()) replaceView(panelId, (v) => ({ ...v, args }));
  };

  const onKey = (e: React.KeyboardEvent<HTMLElement>) => {
    const k = e.key.toLowerCase();
    if (!((e.ctrlKey || e.metaKey) && k === "k")) e.stopPropagation(); // typing must not reach panel keys; Ctrl+K still opens the command line
    if (e.key === "Escape") {
      e.preventDefault();
      (e.currentTarget as HTMLElement).blur();
    } else if (k === "s" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void save();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void run();
    } else if (e.key === "Tab" && e.currentTarget === box.current) {
      e.preventDefault();
      const t = e.currentTarget as HTMLTextAreaElement;
      const next = t.value.slice(0, t.selectionStart) + "    " + t.value.slice(t.selectionEnd);
      const at = t.selectionStart + 4;
      setText(next);
      requestAnimationFrame(() => t.setSelectionRange(at, at));
    }
  };

  if (!valid) return <div className="fn"><div className="err">NAMES ARE 1-40 LETTERS, DIGITS, _ OR -: BT EDIT &lt;NAME&gt;</div></div>;
  const dirty = saved !== null && (saved === "new" || saved.code !== text);
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">BT EDIT {name}</span>{" "}
        <span className="dim">
          {saved === null ? "LOADING…" : saved === "new" ? "NEW PYTHON STRATEGY" : isRule ? "SAVED RULE" : "SAVED PYTHON STRATEGY"}
          {dirty && saved !== null ? " · UNSAVED CHANGES" : ""} · CTRL+S SAVE · CTRL+ENTER SAVE AND RUN · TAB INDENTS · ESC LEAVES THE BOX
        </span>
      </div>
      <div className="line dim">ALLOWED IMPORTS: numpy pandas math statistics typing dataclasses functools itertools collections datetime · NO FILES, NO NETWORK · 60 S / 1 GB PER RUN</div>
      <div className="import editor">
        <textarea ref={box} spellCheck={false} aria-label="strategy code" value={text} disabled={saved === null} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} />
      </div>
      <div className="line">
        RUN <input className="runline" aria-label="run line" value={runLine} spellCheck={false} onChange={(e) => setRunLine(e.target.value.toUpperCase())} onKeyDown={onKey} />
        <span className="dim"> SYMBOLS [1D|1W] [RANGE] [SHORT] [FEES=bps] [SLIP=bps] [CASH=n] [BENCH=sym]</span>
      </div>
      {msg && <pre className={msg.cls === "err" ? "err desc" : "dim desc"}>{msg.text}</pre>}
    </div>
  );
}
