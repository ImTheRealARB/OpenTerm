import { setMode, settingsStore } from "../settings/runtime";
import type { Mode } from "../settings/schema";
import { useStore } from "../state/store";
import { chromeKeyDown, focusCommandLine } from "./chrome";

const LABEL: Record<Mode, string> = { terminal: "TERMINAL", gui: "GUI" };

/**
 * "TERMINAL | GUI" control in the status bar: the current shell is highlighted, clicking the other one switches
 * and saves it like any setting (`setMode` -> settings store -> localStorage mirror -> server). Keyboard users
 * have the `toggleMode` binding (Alt+G) and `SETTINGS MODE GUI|TERMINAL`; the buttons also work with Tab + Enter in GUI mode.
 */
export function ModeToggle() {
  const mode = useStore(settingsStore, (s) => s.mode);
  const button = (m: Mode) => (
    <button
      type="button"
      data-testid={`mode-${m}`}
      className={"mt-btn" + (mode === m ? " on" : "")}
      aria-pressed={mode === m}
      onClick={() => {
        if (mode !== m) setMode(m);
        focusCommandLine();
      }}
    >
      {LABEL[m]}
    </button>
  );
  return (
    <span className="mode-toggle" role="group" aria-label="Interface mode" onKeyDown={chromeKeyDown}>
      {button("terminal")}
      <span className="dim">|</span>
      {button("gui")}
    </span>
  );
}
