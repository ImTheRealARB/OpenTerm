/**
 * APIKEYS (Phase 11): one row per keyed provider. The panel never receives a key value, only status. A value you type
 * lives in an uncontrolled password input (never in React state or the DOM as an attribute); only its masked form
 * (last 4 characters) is shown while typing, and everything is cleared the moment you save or cancel. Typing in the
 * field stops at the field: it reaches neither the command line nor the command history.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { ApiError } from "../net/core";
import { keysApi } from "../net/keysApi";
import type { KeyRow, KeysPayload } from "../net/types";
import { apiKeysSignup } from "./apikeysSignup";
import { maskKey } from "./apikeysMask";
import { groupRows, isHeaderRow, type HeaderRow } from "./apikeysSections";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import { parseCap, spendLine } from "./spendCap";
import type { FunctionProps } from "./registry";
import { openUrl } from "./secPanel";
import { gridCsv, useCsvExport } from "./tableExport";

const ENV_MSG = "SET IN ENV: CHANGE IT IN .env OR THE ENVIRONMENT";

const STATE_COLOR: Record<string, CellColor> = { OK: "up", MISSING: "dim", UNTESTED: "warn", QUOTA: "warn", INVALID: "err", ERROR: "err" };
const SOURCE_TEXT = (r: KeyRow) => (r.source === "env" ? "SET IN ENV" : r.source === "keyring" ? "KEYRING" : r.source === "dotenv" ? ".ENV FILE" : "");
const checked = (r: KeyRow) => (r.checked_at == null ? "" : `${fmtAge(Math.max(0, Date.now() / 1000 - r.checked_at))} AGO`);

/** A grid row: a provider, or a section header ("AI models") drawn as a full-width band that the cursor skips. */
type Row = KeyRow | HeaderRow;

// Terminal columns (unchanged). The CSV export uses these on the provider rows only, so the file never changes with the mode.
const COLUMNS: Column<KeyRow>[] = [
  { title: "PROVIDER", width: 11, text: (r) => r.name.toUpperCase(), color: () => "acc" },
  { title: "STATE", width: 9, text: (r) => r.state, color: (r) => STATE_COLOR[r.state] ?? "fg" },
  { title: "SOURCE", width: 11, text: SOURCE_TEXT, color: () => "dim" },
  { title: "PURPOSE", width: 44, text: (r) => r.purpose },
  { title: "PH", width: 3, align: "right", text: (r) => String(r.phase), color: () => "dim" },
  { title: "LAST CHECK", width: 10, align: "right", text: checked, color: () => "dim" },
];

/** GUI: plain headers, and no PH column (a build-phase number: developer detail). */
const GUI_TITLES: Record<string, string> = { PROVIDER: "Provider", STATE: "Status", SOURCE: "Stored in", PURPOSE: "What it unlocks", "LAST CHECK": "Last check" };
const GUI_COLUMNS: Column<KeyRow>[] = COLUMNS.filter((c) => c.title !== "PH").map((c) => ({ ...c, title: GUI_TITLES[c.title] ?? c.title, width: Math.max(c.width, (GUI_TITLES[c.title] ?? c.title).length + 1) }));

/** Lets a column that only knows provider rows draw header rows too: the header text goes in the first column, nothing in the rest. */
function withHeaders(cols: Column<KeyRow>[]): Column<Row>[] {
  return cols.map((c, i) => ({
    title: c.title,
    width: c.width,
    align: c.align,
    // (no `flash`: none of these columns uses one)
    text: (r: Row) => (isHeaderRow(r) ? (i === 0 ? r.header : "") : c.text(r)),
    color: (r: Row) => (isHeaderRow(r) ? "acc" : (c.color?.(r) ?? "fg")),
  }));
}
const COLUMNS_ROWS = withHeaders(COLUMNS);
const GUI_COLUMNS_ROWS = withHeaders(GUI_COLUMNS);

interface Edit {
  name: string;
  fields: string[];
  /** Masked form of each field, the only trace of what was typed. */
  masks: string[];
}

interface Msg {
  text: string;
  cls: "dim" | "warn" | "err" | "up";
}

export default function APIKEYS({ panelId, args }: FunctionProps) {
  const [data, setData] = useState<KeysPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg | null>(null);
  const [capEdit, setCapEdit] = useState(false);
  const capInput = useRef<HTMLInputElement | null>(null);
  const grid = useRef<GridHandle>(null);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const keyRows = data?.keys ?? [];
  // Display rows: section headers between the providers. Everything below that indexes the grid uses these.
  const rows = useMemo(() => groupRows(keyRows), [data]); // eslint-disable-line react-hooks/exhaustive-deps -- keyRows is derived from data
  const latest = useLatest({ rows, edit, confirm, capEdit });
  useCsvExport(panelId, () => gridCsv("APIKEYS", COLUMNS, keyRows)); // status only, never a value

  const refresh = useCallback(
    () =>
      keysApi
        .keys()
        .then((d) => {
          setData(d);
          setErr(null);
        })
        .catch((e: ApiError) => setErr(e.message)),
    [],
  );
  const patch = useCallback((row: KeyRow) => setData((d) => (d ? { ...d, keys: d.keys.map((k) => (k.name === row.name ? row : k)) } : d)), []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The argument (or the KEY REQUIRED line's key name) preselects that provider's row once the rows are in.
  const want = (args[0] ?? "").toLowerCase();
  const placedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!data || placedFor.current === want) return;
    placedFor.current = want;
    const i = want ? rows.findIndex((k) => !isHeaderRow(k) && (k.name === want || k.fields.some((f) => f.toLowerCase() === want))) : -1;
    // No (known) argument: the first provider. The grid's `initialSelected={1}` is clamped to 0 while the rows are still
    // empty, which left the cursor on the "AI models" header band.
    grid.current?.moveTo(i >= 0 ? i : rows.findIndex((k) => !isHeaderRow(k)));
  }, [data, want, rows]);

  const closeEdit = () => {
    for (const el of inputs.current) if (el) el.value = ""; // nothing typed survives
    inputs.current = [];
    setEdit(null);
  };

  const save = async () => {
    const ed = latest.current.edit;
    if (!ed) return;
    const fields: Record<string, string> = {};
    ed.fields.forEach((f, i) => {
      const v = inputs.current[i]?.value ?? "";
      if (v) fields[f] = v;
    });
    closeEdit();
    if (!Object.keys(fields).length) {
      setMsg({ text: "NOTHING TYPED: NOTHING SAVED", cls: "warn" });
      return;
    }
    setMsg({ text: `SAVING ${ed.name.toUpperCase()} AND TESTING…`, cls: "dim" });
    try {
      const row = await keysApi.putKey(ed.name, fields);
      patch(row);
      setMsg({ text: `${ed.name.toUpperCase()} SAVED: ${row.state}${row.detail ? ` (${row.detail})` : ""}`, cls: row.state === "OK" ? "up" : "warn" });
      void refresh();
    } catch (e) {
      const a = e as ApiError;
      setMsg({ text: `SAVE FAILED: ${a.message}${a.detail ? ` (${a.detail})` : ""}`, cls: "err" });
    }
  };

  const test = async (r: KeyRow) => {
    setMsg({ text: `TESTING ${r.name.toUpperCase()}…`, cls: "dim" });
    try {
      const row = await keysApi.testKey(r.name);
      patch(row);
      setMsg({ text: `${r.name.toUpperCase()}: ${row.state}${row.detail ? ` (${row.detail})` : ""}`, cls: row.state === "OK" ? "up" : "warn" });
    } catch (e) {
      const a = e as ApiError;
      setMsg({ text: `TEST FAILED: ${a.message}${a.detail ? ` (${a.detail})` : ""}`, cls: "err" });
    }
  };

  const remove = async (r: KeyRow) => {
    try {
      patch(await keysApi.deleteKey(r.name));
      setMsg({ text: `${r.name.toUpperCase()} DELETED`, cls: "dim" });
    } catch (e) {
      const a = e as ApiError;
      setMsg({ text: `DELETE FAILED: ${a.message}${a.detail ? ` (${a.detail})` : ""}`, cls: "err" });
    }
  };

  const saveCap = async () => {
    const text = capInput.current?.value ?? "";
    const cap = parseCap(text);
    if (cap === null) {
      setMsg({ text: "CAP MUST BE US$0-1000, E.G. 2.50", cls: "err" });
      return;
    }
    setCapEdit(false);
    try {
      const spend = await keysApi.putLlmCap(cap);
      setData((d) => (d ? { ...d, spend } : d));
      setMsg({ text: `AI SPEND CAP SET: US$${spend.cap.toFixed(2)} PER DAY`, cls: "up" });
    } catch (e) {
      const a = e as ApiError;
      setMsg({ text: `CAP NOT SAVED: ${a.message}${a.detail ? ` (${a.detail})` : ""}`, cls: "err" });
    }
  };

  usePanelRefresh(panelId, () => { void refresh(); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, edit: ed, confirm: c, capEdit: ce } = latest.current;
        if (ce) {
          if (e.key === "Escape") setCapEdit(false);
          return e.key === "Escape";
        }
        if (ed) {
          // The field normally holds focus and handles its own keys; this covers focus that was clicked away.
          if (e.key === "Escape") {
            closeEdit();
            return true;
          }
          return false;
        }
        const sel = cur[g?.selected() ?? -1];
        const r = sel && !isHeaderRow(sel) ? sel : undefined; // a header row is never acted on
        if (c && !(c === r?.name && (e.key === "d" || e.key === "Delete"))) setConfirm(null);
        if (navKey(e, g, cur.length, (i) => isHeaderRow(cur[i]))) return true;
        switch (e.key) {
          case "Enter":
            if (!r) return true;
            if (r.source === "env") setMsg({ text: ENV_MSG, cls: "warn" });
            else {
              setMsg(null);
              setEdit({ name: r.name, fields: r.fields, masks: r.fields.map(() => "") });
            }
            return true;
          case "t":
            if (r) void test(r);
            return true;
          case "d":
          case "Delete":
            if (!r) return true;
            if (r.source === "env") setMsg({ text: ENV_MSG, cls: "warn" });
            else if (!r.present) setMsg({ text: `${r.name.toUpperCase()} HAS NO KEY TO DELETE`, cls: "dim" });
            else if (c === r.name) {
              setConfirm(null);
              void remove(r);
            } else setConfirm(r.name);
            return true;
          case "o": {
            const url = r && apiKeysSignup(r.signup);
            if (url) openUrl(url);
            else setMsg({ text: "NO SIGN-UP PAGE FOR THIS PROVIDER", cls: "dim" });
            return true;
          }
          case "c":
            setMsg(null);
            setCapEdit(true);
            return true;
          case "Escape":
            return c !== null;
        }
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- everything is read through `latest`; save/test/remove only set state and call the api
    [panelId, latest],
  );

  const onFieldKey = (e: React.KeyboardEvent<HTMLInputElement>, i: number) => {
    // Typing here must reach neither panel keys nor type-to-command. Modified chords (Ctrl+K, Ctrl+V) pass on.
    if (!(e.ctrlKey || e.altKey || e.metaKey) || e.key === "Escape") e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      closeEdit();
      setMsg({ text: "EDIT CANCELLED: NOTHING SAVED", cls: "dim" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      void save();
    } else if (e.key === "Tab") {
      // Tab cycles within the form (the browser would otherwise leave the panel).
      const n = latest.current.edit?.fields.length ?? 1;
      e.preventDefault();
      inputs.current[(i + (e.shiftKey ? n - 1 : 1)) % n]?.focus();
    }
  };
  const onFieldChange = () =>
    setEdit((ed) => (ed ? { ...ed, masks: ed.fields.map((_, i) => maskKey(inputs.current[i]?.value ?? "")) } : ed));

  const onCapKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!(e.ctrlKey || e.altKey || e.metaKey) || e.key === "Escape") e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      setCapEdit(false);
      setMsg({ text: "CAP UNCHANGED", cls: "dim" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      void saveCap();
    }
  };

  const set = keyRows.filter((r) => r.present).length;
  const spend = data?.spend;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">API KEYS</span> {set} SET · {keyRows.length - set} MISSING
        {data === null && !err && <span className="dim"> · LOADING…</span>}
        {err && <span className="err"> · STALE: {err}</span>}
        {confirm && <span className="err"> · DELETE {confirm.toUpperCase()} KEY? PRESS D AGAIN</span>}
        <span className="dim legend"> · J/K MOVE · ENTER EDIT · T TEST · D DELETE · O SIGN UP · C SPEND CAP · E EXPORT · F5</span>
      </div>
      {msg && <div className={msg.cls}>{msg.text}</div>}
      {edit && (
        <div className="keyedit" data-testid="apikeys-edit">
          <div className="acc">EDIT {edit.name.toUpperCase()} · ENTER SAVE + TEST · TAB NEXT FIELD · ESC CANCEL · NOTHING TYPED IS SHOWN BEYOND THE LAST 4 CHARACTERS</div>
          {edit.fields.map((f, i) => (
            <label key={f} className="keyfield">
              <span className="dim">{f}</span>{" "}
              <input
                ref={(el) => {
                  inputs.current[i] = el;
                }}
                type="password"
                autoComplete="new-password"
                autoCapitalize="off"
                spellCheck={false}
                autoFocus={i === 0}
                aria-label={f}
                onKeyDown={(e) => onFieldKey(e, i)}
                onChange={onFieldChange}
              />{" "}
              <span className="acc">{edit.masks[i]}</span>
            </label>
          ))}
        </div>
      )}
      {data?.keys.length === 0 && <div className="dim">NO KEYED PROVIDERS REPORTED BY THE BACKEND.</div>}
      <Grid ref={grid} columns={gui ? GUI_COLUMNS_ROWS : COLUMNS_ROWS} rows={rows} initialSelected={1} band={isHeaderRow} />
      <div className="summary" data-testid="apikeys-spend">
        {spendLine(spend)}
        {capEdit && (
          <label className="keyfield">
            {" "}
            <span className="acc">NEW DAILY CAP US$</span>{" "}
            <input
              ref={capInput}
              type="text"
              inputMode="decimal"
              defaultValue={spend ? spend.cap.toFixed(2) : ""}
              autoFocus
              aria-label="AI spend cap in US dollars per day"
              data-testid="apikeys-cap"
              onKeyDown={onCapKey}
            />{" "}
            <span className="dim">ENTER SAVE · ESC CANCEL</span>
          </label>
        )}
      </div>
    </div>
  );
}
