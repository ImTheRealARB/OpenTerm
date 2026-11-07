import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { getChartIndicators, onChartIndicators, requestIndicator, requestKey, type IndicatorRequest } from "../chart/indicatorBus";
import { CATALOG, resolveParams } from "../chart/library/catalog";
import { validateFormula, MAX_FORMULA_LENGTH } from "../chart/formula";
import { registerPanelKeys } from "../keys/panelKeys";
import type { IndicatorPreset, PresetItem } from "../net/types";
import { presetsApi } from "../net/presetsApi";
import "./ind.css";
import { filterIndicators, parseQuery } from "./indFilter";
import type { FunctionProps } from "./registry";
import { useLatest } from "../state/useLatest";

/**
 * IND: indicator library. Search ~100 indicators (name, plain-English line), Enter adds one to the current chart through
 * `chart/indicatorBus` (a chart answers the request; with no chart open it says so). A formula row accepts custom
 * indicators such as EMA(close,12)-EMA(close,26), validated live with the error position. Named presets save the picked
 * list server-side (kv) and load it back onto the chart.
 *
 * Typing goes to real inputs (search / formula / preset name). Esc in an empty search box leaves it so the panel keys work:
 * F formula, S save preset, L load preset, J/K or arrows move, Enter adds.
 */
type Mode = "browse" | "formula" | "save" | "load";
type Row = { kind: "formula" } | { kind: "ind"; id: string; name: string; category: string; plain: string };

const FORMULA_ROW = { id: "FORMULA", name: "Custom formula", category: "other", plain: "Write your own indicator, e.g. EMA(close,12) - EMA(close,26)." };

const itemLabel = (it: PresetItem) => it.label || (it.formula ? it.formula : `${it.id}${it.params.length ? `(${it.params.join(",")})` : ""}`);

export default function IND({ panelId, args }: FunctionProps) {
  const onChart = useSyncExternalStore(onChartIndicators, getChartIndicators);
  const [mode, setMode] = useState<Mode>("browse");
  const [query, setQuery] = useState(args.join(" "));
  const [sel, setSel] = useState(0);
  const [formula, setFormula] = useState("");
  const [picked, setPicked] = useState<PresetItem[]>([]);
  const [msg, setMsg] = useState<{ text: string; kind: "ok" | "err" | "warn" } | null>(null);
  const [presetName, setPresetName] = useState("");
  const [presets, setPresets] = useState<IndicatorPreset[] | null>(null);
  const [psel, setPsel] = useState(0);
  const search = useRef<HTMLInputElement>(null);
  const formulaInput = useRef<HTMLInputElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const rows: Row[] = useMemo(() => {
    const hits = filterIndicators(CATALOG, query);
    const base: Row[] = hits.map((d) => ({ kind: "ind" as const, id: d.id, name: d.name, category: d.category, plain: d.plain }));
    const wantsFormula = !query.trim() || /form|custom|expr|own/i.test(query);
    return wantsFormula ? [{ kind: "formula" }, ...base] : base;
  }, [query]);
  const fcheck = useMemo(() => (formula.trim() ? validateFormula(formula) : null), [formula]);
  const latest = useLatest({ onChart, rows, sel, mode, query, formula, fcheck, picked, presets, psel, presetName });

  useEffect(() => setSel(0), [query]);
  useEffect(() => {
    if (mode === "browse") search.current?.focus();
    if (mode === "formula") formulaInput.current?.focus();
    if (mode === "save") nameInput.current?.focus();
  }, [mode]);
  useEffect(() => {
    listRef.current?.querySelector(".ind-row.sel")?.scrollIntoView({ block: "nearest" });
  }, [sel, psel, mode]);

  const say = (text: string, kind: "ok" | "err" | "warn" = "ok") => setMsg({ text, kind });

  function emit(req: IndicatorRequest, label: string) {
    const was = latest.current.onChart.includes(requestKey(req));
    const answered = requestIndicator({ ...req, op: "toggle" });
    say(answered ? `${was ? "REMOVED" : "ADDED"} ${label} ${was ? "FROM" : "TO"} CHART` : "OPEN A CHART (GP) FIRST", answered ? "ok" : "warn");
    return answered;
  }

  function addSelected() {
    const { rows: rs, sel: s, query: q } = latest.current;
    const r = rs[s];
    if (!r) return;
    if (r.kind === "formula") {
      setMode("formula");
      return;
    }
    const def = CATALOG.find((d) => d.id === r.id)!;
    const given = parseQuery(q).params;
    const params = given.length ? resolveParams(def, given) : [];
    const label = `${def.id}${params.length ? `(${params.join(",")})` : ""}`;
    setPicked((p) => [...p, { id: def.id, params, label: "" }].slice(0, 20));
    emit({ id: def.id, params: params.length ? params : undefined }, label);
  }

  function addFormula() {
    const { formula: f, fcheck: chk } = latest.current;
    if (!f.trim()) return;
    if (!chk || !chk.ok) {
      say(`ERR: ${chk && !chk.ok ? chk.error : "EMPTY FORMULA"}`, "err");
      return;
    }
    setPicked((p) => [...p, { formula: f.trim(), params: [], label: "" }].slice(0, 20));
    emit({ formula: f.trim() }, f.trim().length > 24 ? `${f.trim().slice(0, 24)}…` : f.trim());
  }

  async function savePreset() {
    const { presetName: n, picked: items } = latest.current;
    if (!n.trim()) return say("ERR: TYPE A PRESET NAME", "err");
    if (!items.length) return say("ERR: NOTHING PICKED YET: ADD INDICATORS FIRST", "err");
    try {
      const saved = await presetsApi.put(n.trim(), items);
      say(`SAVED PRESET ${saved.name} (${saved.items.length})`);
      setMode("browse");
    } catch (e) {
      say(`ERR: ${(e as Error).message}`, "err");
    }
  }

  async function openLoad() {
    setMode("load");
    setPsel(0);
    try {
      const r = await presetsApi.list();
      setPresets(r.presets);
      if (!r.presets.length) say("NO PRESETS SAVED YET: ADD INDICATORS THEN PRESS S", "warn");
    } catch (e) {
      setPresets([]);
      say(`ERR: ${(e as Error).message}`, "err");
    }
  }

  function loadPreset() {
    const { presets: ps, psel: i } = latest.current;
    const p = ps?.[i];
    if (!p) return;
    let answered = false;
    for (const it of p.items) {
      const req: IndicatorRequest = it.formula ? { formula: it.formula, label: it.label } : { id: it.id!, params: it.params.length ? it.params : undefined, label: it.label };
      if (requestIndicator(req)) answered = true;
    }
    setPicked(p.items);
    say(answered ? `LOADED PRESET ${p.name} (${p.items.length}) ONTO CHART` : "OPEN A CHART (GP) FIRST", answered ? "ok" : "warn");
    setMode("browse");
  }

  async function deletePreset() {
    const { presets: ps, psel: i } = latest.current;
    const p = ps?.[i];
    if (!p) return;
    try {
      await presetsApi.remove(p.name);
      setPresets((cur) => (cur ?? []).filter((x) => x.name !== p.name));
      setPsel(0);
      say(`DELETED PRESET ${p.name}`);
    } catch (e) {
      say(`ERR: ${(e as Error).message}`, "err");
    }
  }

  const move = (d: number) => {
    const { mode: m, rows: rs, presets: ps } = latest.current;
    if (m === "load") setPsel((i) => Math.max(0, Math.min((ps?.length ?? 1) - 1, i + d)));
    else setSel((i) => Math.max(0, Math.min(rs.length - 1, i + d)));
  };

  // Panel keys: only reached when no input has focus (inputs stop plain keys from bubbling).
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const m = latest.current.mode;
        switch (e.key) {
          case "ArrowDown": case "j": case "J": move(1); return true;
          case "ArrowUp": case "k": case "K": move(-1); return true;
          case "Enter":
            if (m === "load") loadPreset();
            else if (m === "browse") addSelected();
            return true;
          case "Delete": case "x": case "X":
            if (m === "load") { void deletePreset(); return true; }
            return false;
          case "Escape":
            if (m !== "browse") { setMode("browse"); return true; }
            return false;
          case "s": case "S": if (m === "browse") { setMode("save"); return true; } return false;
          case "f": case "F": if (m === "browse") { setMode("formula"); return true; } return false;
          case "l": case "L": if (m === "browse") { void openLoad(); return true; } return false;
        }
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- everything is read through `latest`; handlers only use setters, refs and `latest`
    [panelId, latest],
  );

  /** Shared input behaviour: plain keys stay inside the box, chords reach the global bindings (Ctrl+K etc). */
  const inputKeys = (onEnter: () => void, onEsc: () => void) => (e: React.KeyboardEvent) => {
    if (!e.ctrlKey && !e.altKey && !e.metaKey) {
      if (e.key !== "Tab") e.stopPropagation();
    }
    if (e.key === "Enter") {
      e.preventDefault();
      onEnter();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onEsc();
    } else if (e.key === "ArrowDown" && latest.current.mode === "browse") {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowUp" && latest.current.mode === "browse") {
      e.preventDefault();
      move(-1);
    }
  };

  return (
    <div className="fn ind" data-testid="ind-panel">
      <div className="line">
        <span className="acc">INDICATOR LIBRARY</span>
        <span> · {rows.filter((r) => r.kind === "ind").length} OF {CATALOG.length}</span>
        <span className="dim legend"> · TYPE TO SEARCH · ↑↓ MOVE · ENTER ADDS TO CHART · "RSI 21" SETS A LENGTH · ESC then F FORMULA · S SAVE PRESET · L LOAD</span>
      </div>

      {mode !== "load" && (
        <input
          ref={search}
          className="ind-input"
          data-testid="ind-search"
          aria-label="Search indicators"
          spellCheck={false}
          autoComplete="off"
          placeholder="SEARCH INDICATORS (name, id, trend, momentum, volume ...)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={inputKeys(
            () => addSelected(),
            () => (query ? setQuery("") : search.current?.blur()),
          )}
        />
      )}

      {mode === "formula" && (
        <div className="ind-box">
          <input
            ref={formulaInput}
            className="ind-input"
            data-testid="ind-formula"
            aria-label="Custom formula"
            spellCheck={false}
            autoComplete="off"
            maxLength={MAX_FORMULA_LENGTH}
            placeholder="FORMULA, e.g. EMA(close,12) - EMA(close,26)   ENTER ADDS · ESC BACK"
            value={formula}
            onChange={(e) => setFormula(e.target.value)}
            onKeyDown={inputKeys(addFormula, () => setMode("browse"))}
          />
          <div data-testid="ind-formula-status" className={fcheck && !fcheck.ok ? "err" : fcheck ? "up" : "dim"}>
            {!fcheck ? "TYPE A FORMULA. columns: open high low close volume · functions: SMA EMA RSI STDEV IF CROSSOVER REF MAX MIN ABS ... or any library id" : fcheck.ok ? "OK" : `ERR: ${fcheck.error}`}
          </div>
          {fcheck && !fcheck.ok && (
            <div className="dim ind-caret" aria-hidden="true">
              {formula}
              <br />
              {" ".repeat(Math.min(fcheck.pos, formula.length))}^
            </div>
          )}
        </div>
      )}

      {mode === "save" && (
        <div className="ind-box">
          <input
            ref={nameInput}
            className="ind-input"
            data-testid="ind-preset-name"
            aria-label="Preset name"
            spellCheck={false}
            autoComplete="off"
            maxLength={40}
            placeholder={`PRESET NAME FOR ${picked.length} PICKED INDICATOR${picked.length === 1 ? "" : "S"}, ENTER SAVES · ESC BACK`}
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            onKeyDown={inputKeys(() => void savePreset(), () => setMode("browse"))}
          />
        </div>
      )}

      <div className="ind-list" ref={listRef} data-testid="ind-list" role="listbox" aria-label="Indicators">
        {mode === "load" ? (
          presets === null ? (
            <div className="dim">LOADING PRESETS…</div>
          ) : presets.length === 0 ? (
            <div className="dim">NO PRESETS. ESC BACK</div>
          ) : (
            presets.map((p, i) => (
              <div key={p.name} role="option" aria-selected={i === psel} className={`ind-row${i === psel ? " sel" : ""}`} onClick={() => setPsel(i)} onDoubleClick={loadPreset}>
                <span className="acc">{p.name}</span> <span className="dim">· {p.items.length} ITEM{p.items.length === 1 ? "" : "S"}: {p.items.map(itemLabel).join(", ")}</span>
              </div>
            ))
          )
        ) : rows.length === 0 ? (
          <div className="dim">NO INDICATOR MATCHES "{query.trim().toUpperCase()}"</div>
        ) : (
          rows.map((r, i) => {
            const d = r.kind === "formula" ? FORMULA_ROW : r;
            const on = r.kind === "ind" && onChart.some((k) => k === `LIB:${r.id}` || k.startsWith(`LIB:${r.id}:`));
            return (
              <div key={d.id} role="option" aria-selected={i === sel} className={`ind-row${i === sel ? " sel" : ""}`} data-id={d.id} onClick={() => setSel(i)} onDoubleClick={addSelected}>
                <span className="acc ind-id">{d.id}</span> {on && <span className="up" data-testid="ind-on">ON </span>}<span>{d.name}</span> <span className="dim">[{d.category}]</span>
                <div className="dim ind-plain">{d.plain}</div>
              </div>
            );
          })
        )}
      </div>

      <div className="line ind-foot">
        <span data-testid="ind-picked" className="dim">
          PICKED {picked.length}: {picked.length ? picked.map(itemLabel).join(", ") : "(none yet)"}
        </span>
      </div>
      <div className={`line ind-msg ${msg ? msg.kind : ""}`} data-testid="ind-msg" role="status">
        {msg ? msg.text : mode === "load" ? "ENTER LOADS · X OR DEL DELETES · ESC BACK" : ""}
      </div>
    </div>
  );
}
