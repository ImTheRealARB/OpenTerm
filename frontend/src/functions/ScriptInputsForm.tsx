/**
 * Shift+I on a GP chart with `SCRIPT=`: the inputs of every script on the chart, as a small form.
 * The fields come from the script itself (`indicator` + `input.*` calls, reported by the chart layer as `ScriptReport.inputs`).
 * Apply writes the values back into the panel's args (`SCRIPT=NAME(14,70)`), so they survive layout save / load and a
 * reload; values equal to the script's default are not written. Pure UI: the caller (GP) owns the args.
 */
import { useState } from "react";
import type { ScriptRef } from "./gpArgs";
import type { ScriptReport } from "../chart/scriptTypes";
import { formText, inputsFromRaw, rawFromTexts } from "../script/inputArgs";

interface Props {
  scripts: ScriptRef[];
  report: ScriptReport;
  /** New raw inputs for every script that changed (name -> positional list). */
  onApply(changes: Record<string, string[]>): void;
  onClose(): void;
}

export function ScriptInputsForm({ scripts, report, onApply, onClose }: Props) {
  // One text per input, per script, starting from what is on the chart now (an override) or the script's default.
  const [texts, setTexts] = useState<Record<string, string[]>>(() => {
    const t: Record<string, string[]> = {};
    for (const s of scripts) t[s.name] = (report[s.name]?.inputs ?? []).map((d, i) => formText(d, s.inputs, i));
    return t;
  });
  const [problems, setProblems] = useState<string[]>([]);

  const apply = () => {
    const changes: Record<string, string[]> = {};
    const bad: string[] = [];
    for (const s of scripts) {
      const defs = report[s.name]?.inputs;
      if (!defs?.length) continue;
      const raw = rawFromTexts(defs, texts[s.name] ?? []);
      const check = inputsFromRaw(defs, raw);
      for (const e of check.errors) bad.push(`${s.name}: ${e}`);
      if (raw.join("\u0001") !== s.inputs.join("\u0001")) changes[s.name] = raw;
    }
    setProblems(bad);
    if (bad.length) return;
    if (Object.keys(changes).length) onApply(changes);
    onClose();
  };

  const reset = () => {
    const t: Record<string, string[]> = {};
    for (const s of scripts) t[s.name] = (report[s.name]?.inputs ?? []).map((d) => formText(d, [], 0));
    setTexts(t);
    setProblems([]);
  };

  const set = (name: string, i: number, v: string) => setTexts((cur) => ({ ...cur, [name]: Object.assign([...(cur[name] ?? [])], { [i]: v }) }));

  // Plain keys belong to the form; Ctrl / Alt / Meta chords bubble so Ctrl+K and the other global keys still work.
  const keys = (e: React.KeyboardEvent) => {
    if (!e.ctrlKey && !e.altKey && !e.metaKey) e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      apply();
    } else if (e.key === "Escape") onClose();
  };

  let first = true;
  return (
    <div className="picker" data-testid="gp-script-inputs">
      <div className="acc">SCRIPT INPUTS · TAB MOVES · ENTER APPLIES · ESC CLOSES</div>
      {scripts.map((s) => {
        const st = report[s.name];
        const defs = st?.inputs ?? [];
        return (
          <div key={s.name}>
            <div>
              {s.name}
              {st?.title ? <span className="dim"> · {st.title}</span> : null}
            </div>
            {!defs.length && <div className="dim">{st?.state === "ready" ? "NO INPUTS" : st?.state === "loading" ? "LOADING…" : "NOT AVAILABLE: SEE THE ERROR ABOVE"}</div>}
            {defs.map((d, i) => {
              const val = texts[s.name]?.[i] ?? "";
              const common = { value: val, onKeyDown: keys, "data-testid": `script-input-${s.name}-${i}`, autoFocus: first && i === 0 };
              if (i === 0) first = false;
              return (
                <div key={`${d.title}:${i}`}>
                  <span className="dim">{d.title.toUpperCase()}</span>{" "}
                  {d.kind === "bool" || d.options ? (
                    <select {...common} onChange={(e) => set(s.name, i, e.target.value)}>
                      {(d.kind === "bool" ? ["true", "false"] : d.options!).map((o) => (
                        <option key={o} value={o}>{o}</option>
                      ))}
                    </select>
                  ) : (
                    <input {...common} onChange={(e) => set(s.name, i, e.target.value)} spellCheck={false} size={12} />
                  )}
                  {d.min !== undefined || d.max !== undefined ? <span className="dim"> ({d.min ?? ""} TO {d.max ?? ""})</span> : null}
                </div>
              );
            })}
          </div>
        );
      })}
      {problems.map((m) => (
        <div className="err" key={m} data-testid="script-input-err">{m}</div>
      ))}
      <div>
        <button type="button" onClick={apply} data-testid="script-input-apply">APPLY</button>{" "}
        <button type="button" onClick={reset}>DEFAULTS</button>{" "}
        <button type="button" onClick={onClose}>CLOSE</button>
      </div>
    </div>
  );
}
