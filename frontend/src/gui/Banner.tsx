import { useState } from "react";
import { setMode } from "../settings/runtime";
import { BANNER_KEY, readFlag, writeFlag } from "./onboarding";
import { chromeKeyDown, focusCommandLine } from "./chrome";

/**
 * One line under the menu bar nudging GUI users toward the faster keyboard shell. The x remembers the dismissal in
 * localStorage (`openterm.guiBanner`), so it stays gone after a reload.
 */
export function Banner() {
  const [shown, setShown] = useState(() => !readFlag(BANNER_KEY));
  if (!shown) return null;
  return (
    <div className="gb" data-testid="gui-banner" role="note" onKeyDown={chromeKeyDown}>
      <span>Switch to Terminal mode for keyboard speed</span>
      <button
        type="button"
        className="pt-b"
        data-testid="gui-banner-switch"
        onClick={() => {
          setMode("terminal");
          focusCommandLine();
        }}
      >
        Switch now
      </button>
      <span className="pt-sp" />
      <button
        type="button"
        className="pt-b"
        data-testid="gui-banner-close"
        aria-label="Dismiss this message"
        title="Dismiss"
        onClick={() => {
          writeFlag(BANNER_KEY);
          setShown(false);
          focusCommandLine();
        }}
      >
        ×
      </button>
    </div>
  );
}
