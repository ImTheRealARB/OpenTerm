import { useEffect, useRef, useState, useTransition } from "react";
import { execute, statusMsg } from "../command/execute";
import { fuzzyRank } from "../command/fuzzy";
import { history } from "../command/history";
import { FUNCTION_LIST } from "../functions/registry";
import { api, prefetch, type SearchHit } from "../net/api";
import { keyDown, keyEchoed } from "../perf/metrics";

interface Suggestion {
  value: string;
  label: string;
  kind: "FUNC" | "RECENT" | "SEC";
}

const SEARCH_DEBOUNCE_MS = 80;

export const commandInputRef: { current: HTMLInputElement | null } = { current: null };

/** The token under the cursor (always the last one) and whether it sits in the security slot. */
function lastToken(text: string): { token: string; securitySlot: boolean } {
  const tokens = text.trimStart().split(/\s+/);
  const token = tokens[tokens.length - 1] ?? "";
  const securitySlot = tokens.length === 1 || (tokens.length === 2 && /^[1-9]:$/.test(tokens[0]));
  return { token: /^[1-9]:$/.test(token) ? "" : token, securitySlot };
}

function functionSuggestions(token: string): Suggestion[] {
  return fuzzyRank(token, FUNCTION_LIST, (f) => `${f.code} ${f.title}`, 8).map((f) => ({
    value: f.code,
    label: f.title + (f.load ? "" : ` (P${f.phase})`),
    kind: "FUNC",
  }));
}

/** Merges the three sources. Short tokens that prefix a function code list functions first. */
function merge(token: string, securitySlot: boolean, hits: SearchHit[] = []): Suggestion[] {
  if (!token) return [];
  const fns = functionSuggestions(token);
  if (!securitySlot) return fns;
  const recent = fuzzyRank(token, history.recentSecurities(), (s) => s, 4).map<Suggestion>((s) => ({
    value: s,
    label: "recent",
    kind: "RECENT",
  }));
  const seen = new Set(recent.map((r) => r.value));
  const secs = hits
    .filter((h) => !seen.has(h.symbol))
    .slice(0, 6)
    .map<Suggestion>((h) => ({
      value: h.symbol,
      label: `${h.name ?? ""}  ${h.exchange ?? ""} ${h.type ?? ""}`.trim(),
      kind: "SEC",
    }));
  const fnFirst = token.length <= 4 && fns.some((f) => f.value.startsWith(token.toUpperCase()));
  return (fnFirst ? [...fns.slice(0, 4), ...recent, ...secs] : [...recent, ...secs, ...fns]).slice(0, 10);
}

export function CommandLine() {
  const input = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Suggestion[]>([]);
  const [sel, setSel] = useState(-1);
  const [focused, setFocused] = useState(false);
  const [, startTransition] = useTransition();
  const searchSeq = useRef(0);
  const searchTimer = useRef(0);

  // Predictive prefetch: a highlighted security will most likely be charted or quoted next.
  useEffect(() => {
    const s = items[sel];
    if (s && s.kind !== "FUNC") prefetch(s.value);
  }, [items, sel]);

  const searchSecurities = (text: string, token: string) => {
    clearTimeout(searchTimer.current);
    const seq = ++searchSeq.current;
    if (!/^[A-Za-z0-9.^=-]{1,20}$/.test(token)) return;
    searchTimer.current = window.setTimeout(() => {
      api
        .search(token)
        .then((env) => {
          // Drop replies for text the user has already changed.
          if (seq !== searchSeq.current || input.current?.value !== text) return;
          startTransition(() => setItems(merge(token, true, env.data)));
        })
        .catch(() => {});
    }, SEARCH_DEBOUNCE_MS);
  };

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
    const { token, securitySlot } = lastToken(v);
    startTransition(() => {
      setItems(merge(token, securitySlot));
      setSel(-1);
    });
    if (securitySlot && token) searchSecurities(v, token);
    else searchSeq.current++;
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
