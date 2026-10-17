import { useRef, useState, useTransition } from "react";
import { execute, statusMsg } from "../command/execute";
import { fuzzyRank } from "../command/fuzzy";
import { history } from "../command/history";
import { FUNCTION_LIST } from "../functions/registry";
import { keyDown, keyEchoed } from "../perf/metrics";

interface Suggestion {
  value: string;
  label: string;
  kind: "FUNC" | "RECENT";
}

export const commandInputRef: { current: HTMLInputElement | null } = { current: null };

/** Suggestions for the token under the cursor (always the last token). */
function suggest(text: string): Suggestion[] {
  const tokens = text.trimStart().split(/\s+/);
  const last = tokens[tokens.length - 1] ?? "";
  if (!last || /^[1-9]:$/.test(last)) return [];
  const isFirst = tokens.length === 1 || (tokens.length === 2 && /^[1-9]:$/.test(tokens[0]));
  const fns = fuzzyRank(last, FUNCTION_LIST, (f) => `${f.code} ${f.title}`, 8).map<Suggestion>((f) => ({
    value: f.code,
    label: f.title + (f.load ? "" : ` (P${f.phase})`),
    kind: "FUNC",
  }));
  if (!isFirst) return fns;
  // Ticker search provider arrives in phase 2; until then, recent securities only.
  const recent = fuzzyRank(last, history.recentSecurities(), (s) => s, 5).map<Suggestion>((s) => ({
    value: s,
    label: "recent security",
    kind: "RECENT",
  }));
  return [...recent, ...fns].slice(0, 10);
}

export function CommandLine() {
  const input = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Suggestion[]>([]);
  const [sel, setSel] = useState(-1);
  const [focused, setFocused] = useState(false);
  const [, startTransition] = useTransition();

  const setValue = (v: string) => {
    const el = input.current!;
    el.value = v;
    el.setSelectionRange(v.length, v.length);
  };

  const accept = (s: Suggestion) => {
    const el = input.current!;
    const v = el.value.replace(/\S*$/, s.value) + " ";
    setValue(v);
    setItems([]);
    setSel(-1);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    keyDown(e.timeStamp);
    const el = e.currentTarget;
    if (e.key === "Enter") {
      e.preventDefault();
      if (execute(el.value, { newPanel: e.shiftKey })) {
        setValue("");
        setItems([]);
        setSel(-1);
      }
    } else if (e.key === "Tab" && !e.shiftKey && items.length) {
      e.preventDefault();
      accept(items[Math.max(0, sel)]);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const dir = e.key === "ArrowDown" ? 1 : -1;
      if (items.length && (sel >= 0 || dir === 1) && el.value) {
        setSel((i) => Math.min(items.length - 1, Math.max(-1, i + dir)));
      } else {
        const h = history.step(dir === 1 ? 1 : -1);
        setValue(h ?? "");
        setItems([]);
      }
    } else if (e.key === "Escape") {
      if (items.length) {
        e.stopPropagation();
        setItems([]);
        setSel(-1);
      }
    }
  };

  const onInput = (e: React.FormEvent<HTMLInputElement>) => {
    keyEchoed();
    const v = e.currentTarget.value;
    if (statusMsg.get()) statusMsg.set(() => null);
    history.resetCursor();
    // Suggestion work is low priority: the native input echo never waits on it.
    startTransition(() => {
      setItems(suggest(v));
      setSel(-1);
    });
  };

  return (
    <div className={"cmd" + (focused ? " focus" : "")}>
      <input
        ref={(el) => {
          input.current = el;
          commandInputRef.current = el;
        }}
        id="cmdline"
        aria-label="Command line"
        autoComplete="off"
        spellCheck={false}
        placeholder="TYPE A COMMAND  e.g. AAPL GP  |  HELP  |  ? FOR SHORTCUTS"
        onKeyDown={onKeyDown}
        onInput={onInput}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          setItems([]);
        }}
      />
      {focused && items.length > 0 && (
        <div className="ac" role="listbox">
          {items.map((s, i) => (
            <div key={s.kind + s.value} className={i === sel ? "on" : ""} role="option" aria-selected={i === sel}>
              <span>{s.value}</span>
              <span className="dim">{s.label}</span>
              <span className="k">{s.kind}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
