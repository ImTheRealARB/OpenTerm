/**
 * IMPORT (Phase 12): your own daily bars as a data source. `IMPORT <SYMBOL>` opens a paste box (Ctrl+O picks a file): the
 * rows are checked as you paste (bt/csvImport.ts, the same rules as the backend), Ctrl+Enter stores them. A stored symbol
 * answers GP, BT and every history request from then on, labelled LOCAL DATA, and shadows a real ticker of the same
 * name. `IMPORT` (or `IMPORT LIST`) lists what is stored; `IMPORT DEL <SYMBOL>` or D twice removes one.
 * Phase 22: intraday CSVs (`IMPORT ES5 TZ=America/New_York` when the times carry no offset) and stored synthetic symbols
 * (`IMPORT SYNTH PAIR = AAPL/MSFT`, then `PAIR GP`); the argument grammar lives in `importArgs.ts`.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { parseBarsCsv } from "../bt/csvImport";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtNum } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { btApi } from "../net/btApi";
import type { BtImported, BtSynth } from "../net/types";
import { parseImportArgs } from "./importArgs";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { errText } from "../net/errText";

const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.^=_-]{0,15}$/;

const COLS: Column<BtImported>[] = [
  { title: "SYMBOL", width: 14, text: (r) => r.symbol, color: () => "acc" },
  { title: "ROWS", width: 8, align: "right", text: (r) => fmtNum(r.rows, 0) },
  { title: "FIRST", width: 12, text: (r) => r.first_date },
  { title: "LAST", width: 12, text: (r) => r.last_date },
  { title: "IMPORTED", width: 10, align: "right", text: (r) => `${fmtAge(Date.now() / 1000 - r.created_at)} AGO`, color: () => "dim" },
  { title: "SOURCE", width: 12, text: (r) => r.label, color: () => "warn" },
];

export default function IMPORT({ panelId, args }: FunctionProps) {
  const act = parseImportArgs(args);
  if (act.kind === "paste") return <Paste symbol={act.symbol} tz={act.tz} />;
  if (act.kind === "list") return <Stored panelId={panelId} del={act.del} />;
  return <Synth act={act} />;
}

/** IMPORT SYNTH ...: one store or delete call, then its answer (the server validates the name and the formula). */
function Synth({ act }: { act: Exclude<ReturnType<typeof parseImportArgs>, { kind: "paste" | "list" }> }) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(act.kind === "error" ? { ok: false, text: act.message } : null);
  const key = JSON.stringify(act);
  useEffect(() => {
    if (act.kind === "synth")
      btApi
        .synthPut(act.name, act.formula)
        .then((r) => setMsg({ ok: true, text: `STORED ${r.name} = ${r.formula} · TRY ${r.name} GP` }))
        .catch((e) => setMsg({ ok: false, text: `ERR: ${errText(e)}` }));
    else if (act.kind === "synthDel")
      btApi
        .synthDelete(act.name)
        .then((r) => setMsg({ ok: true, text: `DELETED ${r.deleted}` }))
        .catch((e) => setMsg({ ok: false, text: `ERR: ${errText(e)}` }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per command (`key` is the command)
  }, [key]);
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">IMPORT SYNTH</span> <span className="dim">· A STORED FORMULA CHARTS LIKE A TICKER, LABELLED WITH ITS FORMULA</span>
      </div>
      <div className={msg ? (msg.ok ? "" : "err") : "dim"}>{msg ? msg.text : "STORING…"}</div>
    </div>
  );
}

function Stored({ panelId, del }: { panelId: number; del?: string }) {
  const [rows, setRows] = useState<BtImported[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [synth, setSynth] = useState<BtSynth[] | null>(null);
  const grid = useRef<GridHandle>(null);
  const latest = useLatest({ rows, confirm });

  const reload = () => {
    btApi
      .synthList()
      .then((r) => setSynth(r.synth))
      .catch((e) => setMsg(`ERR: ${errText(e)}`));
    return btApi
      .imports()
      .then((r) => setRows(r.symbols))
      .catch((e) => setMsg(`ERR: ${errText(e)}`));
  };
  const remove = (sym: string) =>
    btApi
      .deleteImport(sym)
      .then(() => {
        setMsg(`DELETED ${sym}`);
        return reload();
      })
      .catch((e) => setMsg(`ERR: ${errText(e)}`));

  useEffect(() => {
    if (del === undefined) return void reload();
    if (!del) setMsg("USAGE: IMPORT DEL <SYMBOL>");
    else void remove(del).then(reload);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per command
  }, [del]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { rows: r, confirm: c } = latest.current;
        if (!r) return false;
        if (navKey(e, grid.current, r.length)) return true;
        if (e.key.toLowerCase() === "d") {
          const row = r[grid.current?.selected() ?? 0];
          if (!row) return true;
          if (c === row.symbol) {
            setConfirm(null);
            void remove(row.symbol);
          } else setConfirm(row.symbol);
          return true;
        }
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- everything is read through `latest`
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">IMPORT</span>{" "}
        <span className="dim">
          {rows ? `${rows.length} SYMBOLS STORED` : "LOADING…"} · IMPORT &lt;SYMBOL&gt; ADDS ONE (CSV: date,open,high,low,close[,volume]) · D TWICE REMOVES · A STORED SYMBOL SHADOWS A REAL TICKER OF THE SAME NAME
        </span>
        {confirm && <span className="err"> · REMOVE {confirm}? PRESS D AGAIN</span>}
      </div>
      {msg && <div className="dim">{msg}</div>}
      {rows && rows.length > 0 && <Grid ref={grid} columns={COLS} rows={rows} />}
      {rows && !rows.length && <div className="dim">NOTHING IMPORTED YET</div>}
      {synth && synth.length > 0 && (
        <div data-testid="import-synth">
          <div className="line">
            <span className="acc">SYNTHETICS</span> <span className="dim">· IMPORT SYNTH &lt;NAME&gt; = &lt;FORMULA&gt; ADDS · IMPORT SYNTH DEL &lt;NAME&gt; REMOVES</span>
          </div>
          {synth.map((x) => (
            <div key={x.name}>
              <span className="acc">{x.name}</span> = {x.formula} <span className="warn">{x.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Paste({ symbol, tz }: { symbol: string; tz?: string }) {
  const [text, setText] = useState("");
  const [state, setState] = useState<{ k: "idle" } | { k: "saving" } | { k: "done"; rows: number; first: string; last: string; interval?: string } | { k: "failed"; error: string }>({ k: "idle" });
  const box = useRef<HTMLTextAreaElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const parsed = useMemo(() => (text.trim() ? parseBarsCsv(text) : null), [text]);
  const latest = useLatest({ text, parsed });
  const badSymbol = !SYMBOL_RE.test(symbol);

  useEffect(() => {
    box.current?.focus();
    const t = setTimeout(() => box.current?.focus(), 80); // the command line hands focus back after Esc
    return () => clearTimeout(t);
  }, []);

  const store = () => {
    const { text: body, parsed: p } = latest.current;
    if (!p || p.errors.length || p.bars.length < 2) return;
    setState({ k: "saving" });
    btApi
      .importBars(symbol, body, tz)
      .then((r) => setState({ k: "done", rows: r.rows, first: r.first_date, last: r.last_date, interval: r.interval }))
      .catch((e) => setState({ k: "failed", error: errText(e) }));
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) e.stopPropagation(); // typing must not reach panel keys; Ctrl+K still opens the command line
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      store();
    } else if (e.key.toLowerCase() === "o" && e.ctrlKey) {
      e.preventDefault();
      file.current?.click();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.currentTarget.blur();
    }
  };
  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) void f.text().then(setText);
  };

  const preview = parsed && !parsed.errors.length ? parsed.bars : null;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">IMPORT {symbol}</span>{" "}
        <span className="dim">PASTE DAILY OR INTRADAY BARS BELOW (date,open,high,low,close[,volume]) · CTRL+ENTER STORES · CTRL+O CHOOSE FILE · ESC LEAVE THE BOX{tz ? ` · TIMES WITHOUT AN OFFSET READ AS ${tz}` : " · INTRADAY TIMES NEED AN OFFSET (-05:00) OR TZ=<ZONE>"}</span>
      </div>
      {badSymbol && <div className="err">SYMBOL MUST BE 1-16 CHARACTERS: LETTERS, DIGITS AND . ^ = _ -</div>}
      <div className="import">
        <textarea ref={box} spellCheck={false} aria-label="CSV text" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} placeholder="date,open,high,low,close,volume" />
      </div>
      <input ref={file} type="file" accept=".csv,text/csv,text/plain" style={{ display: "none" }} onChange={onFile} data-testid="import-file" />
      {parsed && (
        <div data-testid="import-preview">
          {preview ? (
            <>
              <div className="line">
                <span className="acc">{preview.length} ROWS</span> · {preview[0].t} TO {preview[preview.length - 1].t} · VOLUME {parsed.hasVolume ? "YES" : "NO"}
                {parsed.intraday && <span className="acc"> · INTRADAY (THE SERVER READS THE BAR LENGTH AND ZONE)</span>}
                <span className="warn"> · WILL BE LABELLED LOCAL DATA</span>
              </div>
              <pre className="desc">
                {["DATE        OPEN       HIGH       LOW        CLOSE", ...preview.slice(0, 4).map((b) => `${b.t}  ${[b.o, b.h, b.l, b.c].map((x) => String(x).padEnd(10)).join(" ")}`), preview.length > 4 ? "…" : ""].join("\n")}
              </pre>
            </>
          ) : (
            <div className="err">
              {parsed.errors.length} PROBLEM{parsed.errors.length === 1 ? "" : "S"}, NOTHING WILL BE STORED:
              {parsed.errors.slice(0, 6).map((m) => (
                <div key={m}>{m}</div>
              ))}
            </div>
          )}
        </div>
      )}
      {state.k === "saving" && <div className="dim">STORING…</div>}
      {state.k === "failed" && <div className="err">ERR: {state.error}</div>}
      {state.k === "done" && (
        <div className="line">
          STORED <span className="acc">{symbol}</span>: {state.rows} ROWS {state.first} TO {state.last} · <span className="warn">LOCAL DATA</span>
          {state.interval && state.interval !== "1d" ? ` · ${state.interval.toUpperCase()} BARS: TRY ${symbol} GP 5D ${state.interval.replace("m", "MIN")}` : ` · TRY GP ${symbol} OR BT ${symbol} CLOSE>SMA20`}
        </div>
      )}
    </div>
  );
}
