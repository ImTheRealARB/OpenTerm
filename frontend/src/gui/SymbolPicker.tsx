import { useRef } from "react";
import { runSymbol } from "./run";

/**
 * GUI symbol picker: type a ticker and press Enter to load it into the focused panel.
 * This pass is deliberately a plain box: it does the same thing as typing `AAPL` (or `AAPL GP`) on the command line,
 * via `runSymbol`. Key handling (Esc back to the command line, Ctrl/Alt chords bubbling) comes from the menu bar
 * that contains it (see `chromeKeyDown`).
 */
export function SymbolPicker() {
  const input = useRef<HTMLInputElement>(null);
  return (
    <label className="gm-symbol">
      <span className="gm-symbol-label">SYMBOL</span>
      <input
        ref={input}
        data-testid="gui-symbol"
        type="text"
        spellCheck={false}
        autoComplete="off"
        placeholder="AAPL, then Enter"
        aria-label="Symbol: type a ticker and press Enter to load it into the focused panel"
        onKeyDown={(e) => {
          if (e.key !== "Enter" || e.ctrlKey || e.altKey || e.metaKey) return;
          e.preventDefault();
          // Only clear the box when the command ran; a failed one keeps the text so it can be fixed (like the command line).
          if (runSymbol(e.currentTarget.value) && input.current) input.current.value = "";
        }}
      />
    </label>
  );
}
