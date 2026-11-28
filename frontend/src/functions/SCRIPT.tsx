/**
 * SCRIPT (Phase 25): write, save and import OpenTerm Script, the small language for your own chart indicators and alerts.
 *
 *   SCRIPT                   the list: your saved scripts and the 20 starter examples (Enter opens, N new, I import, E export, D twice deletes)
 *   SCRIPT <NAME>            the editor (a name that does not exist yet starts a new script with that name)
 *   SCRIPT NEW [<EXAMPLE>]   the editor with a new script, or with a copy of an example to save under your own name
 *   SCRIPT IMPORT            a paste box: common chart-script text is converted, then opens in the editor with a report
 *
 * The editor is CodeMirror (colours, undo, auto-complete) loaded on demand: `script/editor.ts` is only reached through a dynamic
 * `import()` below, and it loads the script engine the same way, so neither is in the startup bundle. Same pattern as BT EDIT.
 * While you type, the script is checked 300 ms after the last edit and each problem shows on its line and under the box.
 * Ctrl+S saves. Ctrl+Enter checks, saves and opens `<SYMBOL> GP SCRIPT=<NAME>` in a new panel (the chart). Esc leaves the box
 * so the panel keys work: E exports the text as `<name>.ots`, G adds it to a chart, S saves.
 *
 * Panel text is capitals like the rest of the terminal; the script text itself keeps its own case.
 */
import { useEffect, useMemo, useRef, useState } from "react";
// type-only imports: erased at build time, so they do NOT pull CodeMirror or the engine into this chunk
import type { CheckOutcome, ScriptEditor } from "../script/editor";
import { execute } from "../command/execute";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { downloadText } from "../csv";
import { fmtAge } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import type { ApiError } from "../net/core";
import { errText } from "../net/errText";
import { scriptsApi, type ScriptCard, type ScriptExample, type ScriptRec } from "../net/scriptsApi";
import { useLatest } from "../state/useLatest";
import { replaceView, workspace } from "../state/workspace";
import type { FunctionProps } from "./registry";
import { chartCommand, chartSymbol, exportFileName, parseScriptArgs, scriptName, STARTER } from "./scriptPanelArgs";
import { describeInput, problemText, summarizeReport, type ImportLine } from "./scriptPanelFormat";
import { usePanelMemory } from "./usePanelMemory";

/** Shown when a remount (maximize, restore) put back edits that were never saved. */
const RESTORED = "UNSAVED EDITS RESTORED, NOT SAVED: CTRL+S SAVES THEM";

interface Msg {
  cls: "err" | "dim" | "warn";
  text: string;
}

export default function SCRIPT({ panelId, args }: FunctionProps) {
  const m = parseScriptArgs(args);
  switch (m.mode) {
    case "list":
      return <ScriptList panelId={panelId} />;
    case "import":
      return <ImportBox panelId={panelId} />;
    case "new":
      // `key` gives each example its own component, so SCRIPT NEW A then SCRIPT NEW B in one panel never mixes their text.
      return <NewScript key={m.example ?? ""} panelId={panelId} example={m.example} />;
    case "edit":
      return <Editor key={m.name} panelId={panelId} name={m.name} draftKey={m.name} />;
    case "error":
      return (
        <div className="fn">
          <div className="err">{m.error}</div>
        </div>
      );
  }
}

// ---------------------------------------------------------------------------------------------------------------------
// The list
// ---------------------------------------------------------------------------------------------------------------------

interface Row {
  kind: "MINE" | "EXAMPLE";
  name: string;
  title: string;
  note: string;
}

const COLS: Column<Row>[] = [
  { title: "NAME", width: 24, text: (r) => r.name, color: () => "acc" },
  { title: "KIND", width: 8, text: (r) => r.kind, color: (r) => (r.kind === "MINE" ? "fg" : "dim") },
  { title: "TITLE", width: 26, text: (r) => r.title },
  { title: "ABOUT", width: 100, text: (r) => r.note, color: () => "dim" },
];

function ScriptList({ panelId }: { panelId: number }) {
  const [mine, setMine] = useState<ScriptCard[] | null>(null);
  const [examples, setExamples] = useState<ScriptExample[] | null>(null);
  const [msg, setMsg] = useState<Msg | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);

  // Both lists load together. If one fails the other still shows, and the failure is written on screen (never swallowed).
  const reload = () =>
    Promise.allSettled([scriptsApi.list(), scriptsApi.examples()]).then(([a, b]) => {
      const failed: string[] = [];
      if (a.status === "fulfilled") setMine(a.value.scripts);
      else failed.push(`YOUR SCRIPTS: ${errText(a.reason)}`);
      if (b.status === "fulfilled") setExamples(b.value.examples);
      else failed.push(`EXAMPLES: ${errText(b.reason)}`);
      if (failed.length) setMsg({ cls: "err", text: `ERR: ${failed.join(" · ")}` });
    });
  useEffect(() => {
    void reload();
  }, []);

  const rows = useMemo<Row[] | null>(() => {
    if (mine === null && examples === null) return null;
    return [
      ...(mine ?? []).map((s): Row => ({ kind: "MINE", name: s.name, title: s.title, note: `SAVED ${fmtAge(Date.now() / 1000 - s.updated_at)} AGO` })),
      ...(examples ?? []).map((e): Row => ({ kind: "EXAMPLE", name: e.name, title: e.title, note: e.about })),
    ];
  }, [mine, examples]);
  const latest = useLatest({ rows, confirm, examples });

  /** Saves the selected row's text as `<name>.ots` (an example already has its text; a saved script is read from the server). */
  const exportRow = async (row: Row) => {
    try {
      const source = row.kind === "EXAMPLE" ? latest.current.examples?.find((e) => e.name === row.name)?.source : (await scriptsApi.get(row.name)).source;
      if (source === undefined) throw new Error(`NO TEXT FOR ${row.name}`);
      setMsg({ cls: "dim", text: `EXPORTED ${downloadText(exportFileName(row.name), source)}` });
    } catch (e) {
      setMsg({ cls: "err", text: `ERR: ${errText(e)}` });
    }
  };

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { rows: r, confirm: c } = latest.current;
        const k = e.key.toLowerCase();
        if (k === "n") {
          replaceView(panelId, (v) => ({ ...v, args: ["NEW"] }));
          return true;
        }
        if (k === "i") {
          replaceView(panelId, (v) => ({ ...v, args: ["IMPORT"] }));
          return true;
        }
        if (!r) return false;
        if (navKey(e, grid.current, r.length)) return true;
        const row = r[grid.current?.selected() ?? 0];
        if (!row) return false;
        if (e.key === "Enter") {
          // Your own script opens as it is. An example opens as a COPY, so the starter library never changes.
          replaceView(panelId, (v) => ({ ...v, args: row.kind === "MINE" ? [row.name] : ["NEW", row.name] }));
          return true;
        }
        if (k === "e") {
          void exportRow(row);
          return true;
        }
        if (k === "d") {
          if (row.kind === "EXAMPLE") {
            setMsg({ cls: "dim", text: "THE STARTER EXAMPLES CANNOT BE DELETED" });
            return true;
          }
          if (c === row.name) {
            setConfirm(null);
            scriptsApi
              .remove(row.name)
              .then(() => {
                setMsg({ cls: "dim", text: `DELETED ${row.name}` });
                return reload();
              })
              .catch((err) => setMsg({ cls: "err", text: `ERR: ${errText(err)}` }));
          } else setConfirm(row.name);
          return true;
        }
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- everything is read through `latest`; reload and exportRow only use setters and `latest`
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">SCRIPT</span>{" "}
        <span className="dim">
          {rows ? `${mine?.length ?? 0} SAVED · ${examples?.length ?? 0} EXAMPLES` : "LOADING…"} · ENTER OPENS (AN EXAMPLE OPENS AS A COPY) · N NEW · I IMPORT · E EXPORT · D TWICE DELETES · SCRIPT &lt;NAME&gt; OPENS ONE
        </span>
        {confirm && <span className="err"> · DELETE {confirm}? PRESS D AGAIN</span>}
      </div>
      {msg && <div className={msg.cls}>{msg.text}</div>}
      {mine && !mine.length && <div className="dim">NO SAVED SCRIPTS YET: OPEN AN EXAMPLE TO START FROM ONE, OR PRESS N FOR A BLANK ONE.</div>}
      {rows && rows.length > 0 && <Grid ref={grid} columns={COLS} rows={rows} />}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// New script (blank, or a copy of an example)
// ---------------------------------------------------------------------------------------------------------------------

/** Text the editor starts with when the script is new. */
interface Seed {
  text: string;
  /** Suggested name (an example's own name). */
  name?: string;
  note?: string;
  /** What the importer changed or dropped. */
  report?: readonly ImportLine[];
}

function NewScript({ panelId, example }: { panelId: number; example?: string }) {
  const [seed, setSeed] = useState<Seed | null>(example ? null : { text: STARTER });
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!example) return;
    let live = true;
    scriptsApi
      .examples()
      .then((r) => {
        if (!live) return;
        const ex = r.examples.find((x) => x.name === example);
        if (ex) setSeed({ text: ex.source, name: ex.name, note: `COPY OF THE EXAMPLE ${ex.name}: SAVE IT UNDER YOUR OWN NAME` });
        else setErr(`NO EXAMPLE ${example}: SCRIPT LISTS THEM`);
      })
      .catch((e) => {
        if (live) setErr(`ERR: ${errText(e)}`);
      });
    return () => {
      live = false;
    };
  }, [example]);
  if (err) return <div className="fn"><div className="err">{err}</div></div>;
  if (!seed) return <div className="fn"><div className="dim">LOADING…</div></div>;
  return <Editor panelId={panelId} name={null} seed={seed} draftKey={`new:${example ?? ""}`} />;
}

// ---------------------------------------------------------------------------------------------------------------------
// Import: a paste box, then the editor with the report
// ---------------------------------------------------------------------------------------------------------------------

function ImportBox({ panelId }: { panelId: number }) {
  const [result, setResult] = useState<{ source: string; report: ImportLine[] } | null>(null);
  const [msg, setMsg] = useState<Msg | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  const convert = async () => {
    const text = box.current?.value ?? "";
    if (!text.trim()) return setMsg({ cls: "err", text: "NOTHING TO IMPORT: PASTE THE SCRIPT TEXT FIRST" });
    setMsg({ cls: "dim", text: "CONVERTING…" });
    try {
      // The converter is its own lazy chunk: it is only fetched when someone imports.
      const { importScript } = await import("../script/importer");
      const out = importScript(text) as { source: string; report: ImportLine[] };
      setResult(out);
    } catch (e) {
      setMsg({ cls: "err", text: `IMPORT FAILED: ${errText(e)}` });
    }
  };
  const convertRef = useLatest(convert);

  useEffect(() => {
    if (!result) box.current?.focus();
  }, [result]);

  // Panel keys work once the box is left with Esc: Enter converts.
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.key !== "Enter") return false;
        void convertRef.current();
        return true;
      }),
    [panelId, convertRef],
  );

  if (result) return <Editor key="import" panelId={panelId} name={null} draftKey="import" seed={{ text: result.source, report: result.report }} />;
  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Typing here must not reach panel keys, but Ctrl+K still opens the command line.
    if (!((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      e.currentTarget.blur();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void convert();
    }
  };
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">SCRIPT IMPORT</span>{" "}
        <span className="dim">PASTE A SCRIPT IN COMMON CHART-SCRIPT SYNTAX · CTRL+ENTER CONVERTS (OR ESC, THEN ENTER) · THE REPORT SAYS WHAT CHANGED AND WHAT WAS DROPPED</span>
      </div>
      <div className="import">
        <textarea ref={box} spellCheck={false} aria-label="script text to import" onKeyDown={onKey} />
      </div>
      {msg && <pre className={`${msg.cls} desc`}>{msg.text}</pre>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// The editor
// ---------------------------------------------------------------------------------------------------------------------

/**
 * The CodeMirror box. It owns the editor instance and nothing else: text goes in through `docRef` / the handle, edits and keys
 * come out through the callbacks. CodeMirror is fetched with a dynamic `import()` (that keeps it out of the startup bundle), so
 * until it arrives the box shows "LOADING EDITOR…".
 */
function CodeBox(p: {
  handle: React.RefObject<ScriptEditor | null>;
  /** The text to create the editor with. Read once, when CodeMirror arrives. */
  docRef: React.RefObject<string>;
  /** Take keyboard focus (when the box is ready). */
  active: boolean;
  onChange: (t: string) => void;
  onSave: () => void;
  onRun: () => void;
  onChecked: (o: CheckOutcome) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  // The callbacks change every render; the editor is created once, so it calls them through this ref.
  const cb = useLatest(p);
  // Set when the user presses Esc in the box: the delayed focus retry below must not pull them back in.
  const leftBox = useRef(false);

  useEffect(() => {
    let dead = false; // set by cleanup: a late import must not create an editor for a panel that is gone
    let ed: ScriptEditor | null = null;
    import("../script/editor")
      .then((m) => {
        if (dead || !host.current) return;
        ed = m.createScriptEditor(host.current, {
          doc: cb.current.docRef.current,
          ariaLabel: "script code",
          onChange: (t) => cb.current.onChange(t),
          onSave: () => cb.current.onSave(),
          onRun: () => cb.current.onRun(),
          onEscape: () => {
            leftBox.current = true;
          },
          onChecked: (o) => cb.current.onChecked(o),
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

  // Focus when the box becomes usable. The command line hands focus back after Esc, so try again a moment later; the retry is
  // cancelled by ANY key or click of the user in between (same rule as BT EDIT: a late refocus must not undo the user's action).
  useEffect(() => {
    if (state !== "ready" || !p.active) return;
    leftBox.current = false;
    p.handle.current?.focus();
    const userActed = () => {
      leftBox.current = true;
    };
    const stopWatching = () => {
      window.removeEventListener("keydown", userActed, true);
      window.removeEventListener("pointerdown", userActed, true);
    };
    window.addEventListener("keydown", userActed, true);
    window.addEventListener("pointerdown", userActed, true);
    const t = setTimeout(() => {
      stopWatching();
      if (!leftBox.current) p.handle.current?.focus();
    }, 80);
    return () => {
      clearTimeout(t);
      stopWatching();
    };
  }, [state, p.active, p.handle]);

  return (
    <div className="import editor">
      {state === "loading" && <div className="dim">LOADING EDITOR…</div>}
      {state === "failed" && <div className="err">ERR: THE EDITOR FAILED TO LOAD (RELOAD THE PAGE)</div>}
      {/* CodeMirror builds its DOM inside this div. */}
      <div ref={host} className="editor-host" />
    </div>
  );
}

/**
 * `name` = a script that should exist on the server (null = a new script made from `seed`). A name the server does not know yet
 * starts a new script with that name. `draftKey` keys the unsaved text in panel memory, so maximizing the panel keeps it.
 */
function Editor({ panelId, name, seed, draftKey }: { panelId: number; name: string | null; seed?: Seed; draftKey: string }) {
  // Unsaved edits live in panel memory too: maximize (and any remount) throws `useState` away. null = matches what was loaded.
  const [kept, setKept] = usePanelMemory<string | null>("SCRIPT", panelId, `draft:${draftKey}`, null);
  const keptRef = useLatest(kept);
  const [keptName, setKeptName] = usePanelMemory<string | null>("SCRIPT", panelId, `name:${draftKey}`, null);

  /** The text a NEW script starts with (a blank script, an example copy, imported text). */
  const initialText = seed?.text ?? STARTER;
  const [saved, setSaved] = useState<ScriptRec | null | "new">(name === null ? "new" : null);
  const [text, setText] = useState(name === null ? (kept ?? initialText) : "");
  const [nameInput, setNameInput] = useState(keptName ?? seed?.name ?? name ?? "");
  const [msg, setMsg] = useState<Msg | null>(() => (kept !== null && name === null ? { cls: "warn", text: RESTORED } : seed?.note ? { cls: "warn", text: seed.note } : null));
  const [outcome, setOutcome] = useState<CheckOutcome | null>(null);
  const handle = useRef<ScriptEditor | null>(null);
  const docRef = useRef(name === null ? (kept ?? initialText) : "");
  const latest = useLatest({ saved, text, nameInput });

  // An existing script: fetch it. A name the server does not know (404) becomes a new script with that name.
  useEffect(() => {
    if (name === null) return;
    let live = true;
    scriptsApi
      .get(name)
      .then((s) => {
        if (!live) return;
        const start = keptRef.current ?? s.source;
        docRef.current = start;
        setSaved(s);
        setText(start);
        if (keptRef.current !== null) setMsg({ cls: "warn", text: RESTORED });
      })
      .catch((e: ApiError) => {
        if (!live) return;
        if (e.status === 404) {
          const start = keptRef.current ?? STARTER;
          docRef.current = start;
          setText(start);
          setSaved("new");
          if (keptRef.current !== null) setMsg({ cls: "warn", text: RESTORED });
        } else setMsg({ cls: "err", text: `ERR: ${errText(e)}` });
      });
    return () => {
      live = false;
    };
  }, [name, keptRef]);

  // Mirror the box into panel memory while it differs from what was loaded; saving (or undoing back to it) clears it.
  const baseline = saved === "new" || saved === null ? (name === null ? initialText : STARTER) : saved.source;
  useEffect(() => {
    if (saved === null) return; // still loading: the box is not the user's text yet
    setKept(text === baseline ? null : text);
  }, [text, saved, baseline, setKept]);
  useEffect(() => {
    if (saved === "new") setKeptName(nameInput || null);
  }, [nameInput, saved, setKeptName]);

  /** Saves under the right name. Returns the saved name, or null when it did not save (the reason is on screen). */
  const save = async (): Promise<string | null> => {
    const l = latest.current;
    if (l.saved === null) return null;
    const target = l.saved === "new" ? scriptName(l.nameInput) : l.saved.name;
    if (!target) {
      setMsg({ cls: "err", text: "NOT SAVED: TYPE A NAME FIRST (1-32 OF A-Z 0-9 _ . - AND NOT NEW OR IMPORT)" });
      return null;
    }
    setMsg({ cls: "dim", text: "SAVING…" });
    try {
      const r = await scriptsApi.put(target, l.text);
      if (l.saved === "new") {
        // The script now exists: forget the unsaved draft and reopen the panel as SCRIPT <NAME> (a fresh editor loads it).
        setKept(null);
        setKeptName(null);
        replaceView(panelId, (v) => ({ ...v, args: [r.name] }));
      } else {
        setSaved({ ...l.saved, title: r.title, updated_at: r.updated_at, source: l.text });
        setMsg({ cls: "dim", text: `SAVED ${r.name} · ADD IT TO A CHART: CTRL+ENTER (OR ESC, THEN G)` });
      }
      return r.name;
    } catch (e) {
      setMsg({ cls: "err", text: `NOT SAVED: ${errText(e)}` });
      return null;
    }
  };

  /** Checks, saves, and when the script is fine opens it on a chart in a new panel. */
  const run = async () => {
    // Check FIRST: saving a new script reopens the panel (the editor is rebuilt), which would lose the handle.
    const o = await handle.current?.check();
    const name2 = await save();
    if (!name2) return;
    if (!o || o.kind !== "ok") {
      const why = o?.kind === "errors" ? `${o.errors.length} ERROR${o.errors.length === 1 ? "" : "S"}` : (o?.kind === "failed" ? o.message : "THE CHECK DID NOT RUN");
      setMsg({ cls: "err", text: `SAVED ${name2}, BUT NOT ADDED TO A CHART: FIX THE PROBLEM FIRST (${why})` });
      return;
    }
    // GP reads `SCRIPT=<NAME>`. The symbol is this panel's, else the newest GP chart's, else AAPL.
    execute(chartCommand(chartSymbol(workspace.get().panels, panelId), name2), { newPanel: true });
  };
  // The CodeMirror box is created once, so it calls the newest save/run through this ref.
  const fns = useLatest({ save, run });

  const exportNow = () => {
    const l = latest.current;
    if (l.saved === null) return;
    const file = exportFileName((l.saved === "new" ? scriptName(l.nameInput) : l.saved.name) ?? "script");
    setMsg({ cls: "dim", text: `EXPORTED ${downloadText(file, l.text)}` });
  };
  const exportRef = useLatest(exportNow);

  // Panel keys: they only see keys typed OUTSIDE the box (press Esc first).
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const k = e.key.toLowerCase();
        if (k === "e") exportRef.current();
        else if (k === "g") void fns.current.run();
        else if (k === "s") void fns.current.save();
        else return false;
        return true;
      }),
    [panelId, exportRef, fns],
  );

  // Keys in the name box: same rules as the code box (typing must not reach panel keys; Ctrl+K still opens the command line).
  const onNameKey = (e: React.KeyboardEvent<HTMLElement>) => {
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

  const dirty = saved !== null && saved !== "new" && saved.source !== text;
  const problems = outcome?.kind === "errors" ? outcome.errors : [];
  const report = seed?.report ? summarizeReport(seed.report) : null;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">SCRIPT {saved === "new" ? "NEW" : (name ?? "")}</span>{" "}
        <span className="dim">
          {saved === null ? "LOADING…" : saved === "new" ? "NOT SAVED YET" : "SAVED SCRIPT"}
          {outcome?.kind === "ok" && outcome.title ? ` · ${outcome.title}` : ""}
          {dirty ? " · UNSAVED CHANGES" : ""} · CTRL+S SAVE · CTRL+ENTER SAVE AND ADD TO A CHART · AUTO-COMPLETE WHILE YOU TYPE (CTRL+SPACE) · ESC LEAVES THE BOX · E EXPORT · G CHART
        </span>
      </div>
      {saved === "new" && (
        <div className="line">
          SAVE AS <input className="runline" aria-label="script name" value={nameInput} maxLength={32} spellCheck={false} onChange={(e) => setNameInput(e.target.value.toUpperCase())} onKeyDown={onNameKey} />
          <span className="dim"> 1-32 OF A-Z 0-9 _ . -</span>
        </div>
      )}
      {report && (
        <div className="line" data-testid="script-import-report">
          <span className="acc">IMPORT REPORT</span> <span className="dim">{report.headline}</span>
          {report.lines.map((l) => (
            <div key={l} className={l.includes(" DROPPED") ? "err" : "warn"}>{l}</div>
          ))}
          {report.more > 0 && <div className="dim">… AND {report.more} MORE</div>}
        </div>
      )}
      {saved !== null && (
        <CodeBox
          handle={handle}
          docRef={docRef}
          active
          onChange={setText}
          onSave={() => void fns.current.save()}
          onRun={() => void fns.current.run()}
          onChecked={setOutcome}
        />
      )}
      {problems.map((p) => (
        <div key={`${p.line}:${p.col}:${p.msg}`} className="err">{problemText(p)}</div>
      ))}
      {outcome?.kind === "failed" && <pre className="err desc">{outcome.message}</pre>}
      {outcome?.kind === "ok" && (
        <div className="line" data-testid="script-inputs">
          <span className="acc">SETTINGS</span>{" "}
          <span className="dim">
            {outcome.inputs.length ? `${outcome.inputs.length} (SET THEM ON THE CHART)` : "NONE"}
            {outcome.usesLib ? " · USES THE INDICATOR LIBRARY (CHART ONLY FOR NOW)" : ""}
          </span>
          {outcome.inputs.map((i, n) => (
            <div key={n} className="dim">{describeInput(i)}</div>
          ))}
        </div>
      )}
      {msg && <pre className={`${msg.cls} desc`}>{msg.text}</pre>}
    </div>
  );
}
