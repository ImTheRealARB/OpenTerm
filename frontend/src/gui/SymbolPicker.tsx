import { useEffect, useId, useRef, useState } from "react";
import { enterTarget } from "./companySearch";
import { runSymbol } from "./run";
import { useCompanies } from "./useCompanies";

/**
 * GUI symbol picker: type a ticker OR a company name ("apple", "tesla") and load it into the focused panel.
 *
 * Under the box a suggestion list (role="listbox") shows matching stocks as "AAPL  Apple Inc.".
 *   ArrowDown / ArrowUp  move through the suggestions       Enter  runs the highlighted one (or the typed text)
 *   click                runs that suggestion               Esc    closes the list (a second Esc goes back to the command line)
 * Running a symbol is `runSymbol` = the same thing as typing `AAPL` on the command line (DES, or the panel's own function).
 * Key handling for Esc / Ctrl / Alt chords comes from the menu bar that contains it (see `chromeKeyDown`).
 */
export function SymbolPicker() {
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(-1); // highlighted suggestion, -1 = none
  const [closed, setClosed] = useState(false); // Esc hides the list until the text changes
  const hits = useCompanies(text, focused);
  const showList = focused && !closed && hits.length > 0;
  // "No match" is only said after the search has had 1.5 s to answer, so a slow answer never flashes it.
  const [waitedFor, setWaitedFor] = useState("");
  const q = text.trim();
  useEffect(() => {
    const t = setTimeout(() => setWaitedFor(q), 1500);
    return () => clearTimeout(t);
  }, [q]);
  const showNone = focused && !closed && !hits.length && waitedFor === q && q.length > 1;

  /** Loads a stock and empties the box (only when the command ran: a failed one keeps the text so it can be fixed). */
  const go = (value: string) => {
    if (runSymbol(value)) {
      setText("");
      setActive(-1);
    }
  };

  return (
    <div className="gm-symbol">
      <label>
        <span className="gm-symbol-label">SYMBOL</span>
        <input
          ref={input}
          data-testid="gui-symbol"
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
          spellCheck={false}
          autoComplete="off"
          placeholder="Company or ticker"
          aria-label="Symbol: type a company name or ticker, pick a suggestion or press Enter to load it into the focused panel"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setActive(-1);
            setClosed(false);
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (e.ctrlKey || e.altKey || e.metaKey) return;
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              if (!hits.length) return;
              e.preventDefault();
              e.stopPropagation();
              setClosed(false);
              const n = hits.length;
              setActive((i) => (e.key === "ArrowDown" ? (i + 1) % n : (i - 1 + n) % n));
            } else if (e.key === "Escape" && showList) {
              // First Esc only closes the list; the menu bar's handler (back to the command line) does not see it.
              e.preventDefault();
              e.stopPropagation();
              setClosed(true);
              setActive(-1);
            } else if (e.key === "Enter") {
              e.preventDefault();
              go(showList && active >= 0 ? hits[active].symbol : enterTarget(text, hits));
            }
          }}
        />
      </label>
      {showNone && (
        <div className="gm-suggest gm-none" role="status">
          No match. Enter tries it as a ticker.
        </div>
      )}
      {showList && (
        <ul className="gm-suggest" role="listbox" id={listId} aria-label="Matching stocks">
          {hits.map((h, i) => (
            <li
              key={h.symbol}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "on" : undefined}
              // mousedown (not click) is where focus would leave the box and close the list, so keep focus here.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => go(h.symbol)}
            >
              <b>{h.symbol}</b> <span>{h.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
