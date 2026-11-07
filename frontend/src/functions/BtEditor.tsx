/**
 * BT EDIT / BT LOAD (Phase 12 step 4B): the Python strategy editor. `BT EDIT` lists saved strategies (Enter opens one, D
 * twice deletes); `BT EDIT <NAME>` opens or creates one. The box holds a `SignalEngine` (spec section 1) for a Python
 * strategy, or the rule text for a saved rule. Ctrl+S saves (the server checks the code against the sandbox allowlist and
 * says why it refuses), Ctrl+Enter saves and runs it with the RUN line below the box (`SYMBOLS [1D|1W] [RANGE] [OPTIONS]`),
 * which opens the result as `BT <SYMBOLS> @<NAME> ...`. Tab inserts four spaces; Esc leaves the box.
 *
 * The box is CodeMirror (line numbers, Python colours, undo, bracket matching), loaded on demand: `bt/codeEditor.ts` is only
 * ever reached through a dynamic `import()` below, so it is a separate chunk downloaded the first time an editor opens.
 * While you type, the server's sandbox check runs 400 ms after the last edit and a problem is shown on its line and under the box.
 * A name that does not exist yet first shows the starter templates (GET /api/bt/templates); `T` (after Esc) reopens them.
 */
import { useEffect, useRef, useState } from "react";
// type-only import: erased at build time, so it does NOT pull CodeMirror into this chunk
import type { CodeEditor } from "../bt/codeEditor";
import { isBtRun, parseBtArgs } from "../bt/ruleParse";
import { parseSandboxError, type SandboxError } from "../bt/sandboxError";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { PanelNote } from "../components/PanelNote";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { btApi } from "../net/btApi";
import { ApiError } from "../net/core";
import type { BtStrategy, BtStrategyCard, BtTemplate } from "../net/types";
import { replaceView } from "../state/workspace";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import { errText as netErrText } from "../net/errText";

/** This editor joins the server's detail with a colon ("NOT SAVED: LINE 3: ..."). */
const errText = (e: unknown) => netErrText(e, "colon");
export const NAME_RE = /^[a-z0-9_-]{1,40}$/;

const TEMPLATE_COLS: Column<BtTemplate>[] = [
  { title: "TITLE", width: 28, text: (t) => t.title, color: () => "acc" },
  { title: "SUMMARY", width: 90, text: (t) => t.summary },
];

/** How long to wait after the last keystroke before asking the server to check the code. */
const CHECK_DELAY_MS = 400;

const COLS: Column<BtStrategyCard>[] = [
  { title: "NAME", width: 24, text: (s) => s.name, color: () => "acc" },
  { title: "KIND", width: 8, text: (s) => (s.kind === "rule" ? "RULE" : "PYTHON") },
  { title: "SAVED", width: 12, align: "right", text: (s) => `${fmtAge(Date.now() / 1000 - s.updated_at)} AGO`, color: () => "dim" },
];

export default function BtEditor({ panelId, name }: { panelId: number; name?: string }) {
  // `key` makes React build a fresh Editor when the name changes (BT EDIT a, then BT EDIT b in the same panel), so the
  // CodeMirror instance, the undo history and the pending checks of the first strategy never leak into the second.
  return name ? <Editor key={name.toLowerCase()} panelId={panelId} name={name.toLowerCase()} /> : <Saved panelId={panelId} />;
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
      {rows && !rows.length && (
        <PanelNote kind="empty" hint="Create one: BT EDIT MYSTRAT (Python editor) or BT SAVE MYRULE SMA20>SMA50 (a rule). Run it with BT AAPL @MYRULE 1D 5Y.">
          NO SAVED STRATEGIES YET
        </PanelNote>
      )}
    </div>
  );
}

/**
 * The CodeMirror box. It owns the editor instance and nothing else: text goes in through `docRef` / the handle, edits and
 * keys come out through the callbacks. Mounted as soon as the strategy is known; CodeMirror itself is fetched with a dynamic
 * `import()` (that is what keeps it out of the startup bundle), so until it arrives the box shows "LOADING EDITOR…".
 */
function CodeBox(p: {
  handle: React.RefObject<CodeEditor | null>;
  /** The text to create the editor with. Read once, when CodeMirror arrives, so it reflects any template picked while loading. */
  docRef: React.RefObject<string>;
  python: boolean;
  hidden: boolean;
  /** Take keyboard focus (when the box is visible and ready). */
  active: boolean;
  error: SandboxError | null;
  onChange: (t: string) => void;
  onSave: () => void;
  onRun: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  // The callbacks change every render; the editor is created once, so it calls them through this ref.
  const cb = useLatest(p);
  // Set when the user presses Esc in the box: the delayed focus retry below must not pull them back in.
  const leftBox = useRef(false);

  useEffect(() => {
    let dead = false; // set by cleanup: a late import must not create an editor for a panel that is gone
    let ed: CodeEditor | null = null;
    import("../bt/codeEditor")
      .then((m) => {
        if (dead || !host.current) return;
        ed = m.createCodeEditor(host.current, {
          doc: cb.current.docRef.current,
          python: cb.current.python,
          ariaLabel: "strategy code",
          onChange: (t) => cb.current.onChange(t),
          onSave: () => cb.current.onSave(),
          onRun: () => cb.current.onRun(),
          // The editor has already blurred itself; panel keys (T) take over from here.
          onEscape: () => {
            leftBox.current = true;
          },
        });
        p.handle.current = ed;
        setState("ready");
      })
      .catch(() => {
        if (!dead) setState("failed");
      });
    return () => {
      dead = true;
      ed?.destroy();
      p.handle.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- created once per mount on purpose: everything else is read through `cb`
  }, []);

  // Show / clear the inline error marker whenever the error (or the editor's readiness) changes.
  useEffect(() => {
    if (state !== "ready") return;
    if (p.error && p.error.line !== null) p.handle.current?.setError(p.error.line, p.error.message);
    else p.handle.current?.setError(null);
  }, [p.error, state, p.handle]);

  // Focus when the box becomes usable. The command line hands focus back after Esc, so try again a moment later,
  // unless the user has pressed Esc in the box since (on a busy machine the retry can land after that Esc).
  useEffect(() => {
    if (state !== "ready" || !p.active) return;
    leftBox.current = false;
    p.handle.current?.focus();
    const t = setTimeout(() => {
      if (!leftBox.current) p.handle.current?.focus();
    }, 80);
    return () => clearTimeout(t);
  }, [state, p.active, p.handle]);

  return (
    <div className="import editor" style={p.hidden ? { display: "none" } : undefined}>
      {state === "loading" && <div className="dim">LOADING EDITOR…</div>}
      {state === "failed" && <div className="err">ERR: THE EDITOR FAILED TO LOAD (RELOAD THE PAGE)</div>}
      {/* CodeMirror builds its DOM inside this div. */}
      <div ref={host} className="editor-host" />
    </div>
  );
}

function Editor({ panelId, name }: { panelId: number; name: string }) {
  const [saved, setSaved] = useState<BtStrategy | null | "new">(null);
  const [text, setText] = useState("");
  const [runLine, setRunLine] = useState("AAPL 1D 5Y");
  const [msg, setMsg] = useState<{ cls: string; text: string } | null>(null);
  // Sandbox problem (from the live check or a refused save): drawn on its line AND written under the box.
  const [sbx, setSbx] = useState<SandboxError | null>(null);
  const [checkErr, setCheckErr] = useState<string | null>(null);
  // "edit" = the code box; "choose" = the template list. A new name starts in "choose".
  const [view, setView] = useState<"edit" | "choose">("edit");
  const [templates, setTemplates] = useState<BtTemplate[] | null>(null);
  // First T on unsaved changes only warns; the second replaces.
  const [armed, setArmed] = useState(false);
  const handle = useRef<CodeEditor | null>(null);
  const docRef = useRef("");
  const grid = useRef<GridHandle>(null);
  const checkSeq = useRef(0);
  const latest = useLatest({ text, runLine, saved, view, templates, armed });
  const valid = NAME_RE.test(name);

  const loadTemplates = () =>
    btApi
      .templates()
      .then((r) => setTemplates(r.templates))
      .catch((e) => {
        setMsg({ cls: "err", text: `ERR: TEMPLATES: ${errText(e)}` });
        // Nothing to choose from: leave the chooser rather than show an empty list with no way out.
        setView("edit");
      });

  useEffect(() => {
    if (!valid) return;
    let live = true;
    btApi
      .strategy(name)
      .then((s) => {
        if (!live) return;
        docRef.current = s.code;
        setSaved(s);
        setText(s.code);
      })
      .catch((e: ApiError) => {
        if (!live) return;
        if (e.status === 404) {
          // A name that does not exist yet: the box starts empty, hidden behind the template chooser.
          docRef.current = "";
          setSaved("new");
          setView("choose");
          void loadTemplates();
        } else setMsg({ cls: "err", text: `ERR: ${errText(e)}` });
      });
    return () => {
      live = false;
    };
    // loadTemplates only uses setters
  }, [name, valid]);

  const isRule = saved !== null && saved !== "new" && saved.kind === "rule";
  const loaded = saved !== null;

  // Live sandbox check: 400 ms after the last edit ask the server whether the code passes the sandbox rules.
  // Every edit re-runs this effect, which bumps `checkSeq`; an answer that comes back for an older edit is ignored.
  useEffect(() => {
    if (!loaded || isRule) return;
    const seq = ++checkSeq.current;
    const code = text;
    const t = setTimeout(() => {
      btApi
        .check(code)
        .then((r) => {
          if (seq !== checkSeq.current) return; // a newer edit is already being checked
          setCheckErr(null);
          setSbx(r.ok ? null : parseSandboxError(r.error));
        })
        .catch((e) => {
          if (seq !== checkSeq.current) return;
          setCheckErr(`CHECK UNAVAILABLE: ${errText(e)}`); // shown, never silently skipped
        });
    }, CHECK_DELAY_MS);
    return () => clearTimeout(t);
  }, [text, loaded, isRule]);

  const onChange = (t: string) => {
    setText(t);
    setArmed(false);
  };

  const save = async (): Promise<boolean> => {
    const { text: body } = latest.current;
    setMsg({ cls: "dim", text: "SAVING…" });
    try {
      const r = await btApi.putStrategy(name, isRule ? { rule: body.trim() } : { code: body });
      setSaved({ name: r.name, kind: r.kind, code: isRule ? body.trim() : body, updated_at: r.updated_at });
      setSbx(null);
      setMsg({ cls: "dim", text: `SAVED ${name} (${r.kind === "rule" ? "RULE" : "PYTHON"}) · RUN IT: BT <SYMBOLS> @${name} 1D 5Y OR CTRL+ENTER` });
      return true;
    } catch (e) {
      setMsg({ cls: "err", text: `NOT SAVED: ${errText(e)}` });
      // The server puts the sandbox's reason (with its LINE n) in the error detail: show it on the line too.
      const a = e as ApiError;
      if (!isRule && a.detail) setSbx(parseSandboxError(a.detail));
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
  // The CodeMirror box is created once, so it must call the newest save/run (they close over `isRule`, `name` ...).
  const fns = useLatest({ save, run });

  /** Opens the template list (for a saved strategy via T; a new name is already there). */
  const openChooser = () => {
    setArmed(false);
    setView("choose");
    if (!latest.current.templates) void loadTemplates();
  };
  /** Puts a template's code in the box. Marks the strategy unsaved (it differs from the saved code). */
  const pick = (t: BtTemplate) => {
    docRef.current = t.code; // read when CodeMirror arrives, if the user picked before it finished loading
    handle.current?.setDoc(t.code); // already there: replace the text (this also clears the inline marker)
    setText(t.code);
    setSbx(null);
    setCheckErr(null);
    setView("edit");
  };

  // Panel keys (they only see keys typed OUTSIDE the code box: press Esc first). Registered once; state is read via `latest`.
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const l = latest.current;
        if (l.view === "choose") {
          const list = l.templates;
          if (!list) return false;
          if (navKey(e, grid.current, list.length)) return true;
          if (e.key === "Enter") {
            const t = list[grid.current?.selected() ?? 0];
            if (t) pick(t);
            return true;
          }
          // Esc backs out to the box, but only when there is something to go back to (a new name has no code yet).
          if (e.key === "Escape" && l.saved !== "new") {
            setView("edit");
            return true;
          }
          return false;
        }
        if (e.key.toLowerCase() !== "t") {
          if (l.armed) setArmed(false);
          return false;
        }
        if (l.saved === null) return false;
        if (l.saved !== "new" && l.saved.kind === "rule") {
          setMsg({ cls: "err", text: "TEMPLATES ARE PYTHON STRATEGIES: A SAVED RULE CANNOT BE REPLACED BY ONE" });
          return true;
        }
        const dirty = l.saved === "new" || l.saved.code !== l.text;
        if (dirty && l.text !== "" && !l.armed) {
          setArmed(true);
          return true;
        }
        openChooser();
        return true;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- everything is read through `latest`; pick/openChooser only use setters, refs and `latest`
    [panelId, latest],
  );

  // Keys in the RUN line input: same rules as the code box (typing must not reach panel keys; Ctrl+K still opens the command line).
  const onKey = (e: React.KeyboardEvent<HTMLElement>) => {
    const k = e.key.toLowerCase();
    if (!((e.ctrlKey || e.metaKey) && k === "k")) e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      (e.currentTarget as HTMLElement).blur();
    } else if (k === "s" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void save();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void run();
    }
  };

  if (!valid) return <div className="fn"><div className="err">NAMES ARE 1-40 LETTERS, DIGITS, _ OR -: BT EDIT &lt;NAME&gt;</div></div>;
  const dirty = saved !== null && (saved === "new" || saved.code !== text);
  const choosing = view === "choose";
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">BT EDIT {name}</span>{" "}
        <span className="dim">
          {saved === null ? "LOADING…" : saved === "new" ? "NEW PYTHON STRATEGY" : isRule ? "SAVED RULE" : "SAVED PYTHON STRATEGY"}
          {dirty && saved !== null && !choosing ? " · UNSAVED CHANGES" : ""}
          {choosing
            ? ` · ${templates ? "ENTER LOADS THE SELECTED TEMPLATE" : "LOADING TEMPLATES…"}${saved === "new" ? "" : " · ESC BACK TO THE BOX"}`
            : " · CTRL+S SAVE · CTRL+ENTER SAVE AND RUN · TAB INDENTS · ESC LEAVES THE BOX · T (AFTER ESC) TEMPLATES"}
        </span>
      </div>
      <div className="line dim">ALLOWED IMPORTS: numpy pandas math statistics typing dataclasses functools itertools collections datetime · NO FILES, NO NETWORK · 60 S / 1 GB PER RUN</div>
      {armed && <div className="line warn">UNSAVED CHANGES: PRESS T AGAIN TO REPLACE</div>}
      {choosing && templates && templates.length > 0 && <Grid ref={grid} columns={TEMPLATE_COLS} rows={templates} />}
      {saved !== null && (
        <CodeBox
          handle={handle}
          docRef={docRef}
          python={!isRule}
          hidden={choosing}
          active={!choosing}
          error={sbx}
          onChange={onChange}
          onSave={() => void fns.current.save()}
          onRun={() => void fns.current.run()}
        />
      )}
      {!choosing && (
        <div className="line">
          RUN <input className="runline" aria-label="run line" value={runLine} spellCheck={false} onChange={(e) => setRunLine(e.target.value.toUpperCase())} onKeyDown={onKey} />
          <span className="dim"> SYMBOLS [1D|1W] [RANGE] [SHORT] [FEES=bps] [SLIP=bps] [CASH=n] [BENCH=sym]</span>
        </div>
      )}
      {sbx && !choosing && <pre className="err desc">SANDBOX: {sbx.line !== null ? `LINE ${sbx.line}: ` : ""}{sbx.message}</pre>}
      {checkErr && <pre className="err desc">{checkErr}</pre>}
      {msg && <pre className={msg.cls === "err" ? "err desc" : "dim desc"}>{msg.text}</pre>}
    </div>
  );
}
