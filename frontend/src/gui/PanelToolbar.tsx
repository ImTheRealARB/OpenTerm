import { useRef, useState, type MouseEvent } from "react";
import { info } from "../command/status";
import { runItem } from "../components/windowMenuRun";
import type { OptionAction } from "../components/windowMenu";
import { effectiveBindings } from "../keys/keys";
import { dispatchPanelKey } from "../keys/panelKeys";
import { focusPanel, workspace } from "../state/workspace";
import { useStore } from "../state/store";
import { chromeKeyDown, focusCommandLine } from "./chrome";
import { openHelp } from "./helpState";
import { runCommand } from "./run";
import { buttonsFor, expandAsk, keyInit, type ToolbarButton } from "./toolbars";

/**
 * GUI-only button row under a panel's title bar.
 *
 * Left: buttons for this function (`toolbars.ts`), each of which "presses" a key the panel already handles.
 * Right: the same five buttons on every panel: "?" (help drawer), CSV, Refresh, Max/Restore, Close. Those reuse
 * `runItem` from the window-frame menu (components/windowMenuRun.ts), so they do exactly what OPTIONS does.
 *
 * Keyboard: every button is a real <button>, so Tab reaches it and Enter / Space press it. Plain keys typed while a
 * toolbar button has focus must not ALSO reach the panel's key handler (Enter would fire twice), hence `chromeKeyDown`.
 */
export function PanelToolbar({ id, fn, args }: { id: number; fn: string | undefined; args: readonly string[] }) {
  const maximized = useStore(workspace, (s) => s.maximized === id);
  // The button whose inline prompt is open (WL "Add" asks for symbols), or null.
  const [ask, setAsk] = useState<ToolbarButton | null>(null);
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const buttons = buttonsFor(fn, args);

  /** After a MOUSE click let go of the button so the panel's own keys (j/k, Enter...) work right away; keep keyboard focus for Tab users. */
  const afterClick = (e: MouseEvent<HTMLElement>) => {
    if (e.detail > 0) e.currentTarget.blur();
  };

  const press = (b: ToolbarButton, e: MouseEvent<HTMLElement>) => {
    if (b.ask) {
      setText("");
      setAsk(b);
      // The input mounts on the next render; focus it then.
      setTimeout(() => input.current?.focus(), 0);
      return;
    }
    focusPanel(id);
    // Same KeyboardEvent the browser would send for that key; the panel's handler returns false when it has no use for it
    // (a key that needs a loaded chart, a different view of the panel ...).
    if (!dispatchPanelKey(id, new KeyboardEvent("keydown", keyInit(b)))) info(`${b.label.toUpperCase()}: NOT AVAILABLE IN THIS VIEW OR WHILE IT LOADS`);
    afterClick(e);
  };

  const option = (action: OptionAction, label: string, e: MouseEvent<HTMLElement>) => {
    runItem(id, { kind: "action", action, label });
    afterClick(e);
  };

  const submitAsk = () => {
    if (!ask?.ask || text.trim() === "") return;
    focusPanel(id);
    // Runs the equivalent command line text, e.g. "WL TECH ADD AAPL MSFT". A failure keeps the prompt open so the text can be fixed.
    if (runCommand(expandAsk(ask.ask.command, args, text))) setAsk(null);
  };

  if (ask?.ask) {
    return (
      <div className="pt" role="toolbar" aria-label={`Panel ${id}: ${ask.label}`} onKeyDown={chromeKeyDown}>
        <span className="pt-ask-l">{ask.label.toUpperCase()}</span>
        <input
          ref={input}
          className="pt-ask"
          data-testid="pt-ask"
          type="text"
          value={text}
          spellCheck={false}
          autoComplete="off"
          placeholder={ask.ask.prompt}
          aria-label={ask.ask.prompt}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.ctrlKey || e.altKey || e.metaKey) return; // chords bubble (Ctrl+K must still reach the command line)
            if (e.key === "Enter") {
              e.preventDefault();
              submitAsk();
            } else if (e.key === "Escape") {
              setAsk(null); // chromeKeyDown (on the row) then puts focus back on the command line
            }
          }}
        />
        <button type="button" className="pt-b" onClick={submitAsk}>
          Run
        </button>
        <button type="button" className="pt-b" onClick={() => { setAsk(null); focusCommandLine(); }}>
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="pt" role="toolbar" aria-label={`Panel ${id} buttons`} data-testid={`pt-${id}`} onKeyDown={chromeKeyDown}>
      {buttons.map((b) => (
        <button key={b.label} type="button" className="pt-b pt-fn" title={b.title ?? b.label} onClick={(e) => press(b, e)}>
          {b.label}
        </button>
      ))}
      <span className="pt-sp" />
      <button type="button" className="pt-b pt-help" title={`Help for this panel (${effectiveBindings().helpDrawer[0] ?? "no key bound"})`} aria-label="Help for this panel" onClick={(e) => { openHelp(id, e.currentTarget); }}>
        ?
      </button>
      <button type="button" className="pt-b" title="Export the table as CSV (Alt+X)" onClick={(e) => option("exportCsv", "EXPORT CSV", e)}>
        CSV
      </button>
      <button type="button" className="pt-b" title="Reload the panel's data (F5)" onClick={(e) => option("refresh", "REFRESH", e)}>
        Refresh
      </button>
      <button type="button" className="pt-b" title="Maximize or restore this panel (Ctrl+Shift+F)" onClick={(e) => option("maximize", "MAXIMIZE / RESTORE", e)}>
        {maximized ? "Restore" : "Max"}
      </button>
      <button type="button" className="pt-b pt-close" title="Close this panel (Alt+W)" aria-label="Close this panel" onClick={(e) => option("closePanel", "CLOSE PANEL", e)}>
        Close
      </button>
    </div>
  );
}
