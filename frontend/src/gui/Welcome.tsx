import { useEffect, useRef } from "react";
import { useStore } from "../state/store";
import { chromeKeyDown, focusCommandLine } from "./chrome";
import { closeWelcome, onboarding, startTour } from "./onboarding";
import { runCommand } from "./run";

/** AAPL is in the offline fixtures (OPENTERM_FIXTURES=1) as well as live, so these three buttons work in every setup. */
const SAMPLE = "AAPL";

/** The three big first-run buttons. `command` is ordinary command line text, run in the focused panel. */
const CHOICES = [
  { id: "des", label: "Look up a stock", hint: `Company profile and key facts for ${SAMPLE}`, command: `${SAMPLE} DES` },
  { id: "gp", label: "See a chart", hint: `Price chart of ${SAMPLE}; try the range buttons`, command: `${SAMPLE} GP` },
  { id: "wl", label: "Watch my stocks", hint: "Your saved watchlists (create one with the Add button)", command: "WL" },
] as const;

/**
 * First-run welcome card, shown once over the workspace (localStorage `openterm.welcomed`, set by `showWelcome`).
 * Tab moves between the buttons, Enter presses one, Esc closes. It can be shown again from Settings > Show welcome card.
 */
export function Welcome() {
  const open = useStore(onboarding, (s) => s.welcome);
  const first = useRef<HTMLButtonElement>(null);

  // Focus the first button on open so Enter / Tab / Esc work immediately.
  useEffect(() => {
    if (open) first.current?.focus();
  }, [open]);

  if (!open) return null;
  const close = () => {
    closeWelcome();
    focusCommandLine();
  };
  return (
    <div
      className="gw"
      data-testid="welcome-card"
      role="dialog"
      aria-label="Welcome to OpenTerm"
      onKeyDown={(e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return; // chords bubble
        if (e.key === "Escape") {
          e.stopPropagation();
          e.preventDefault();
          close();
          return;
        }
        chromeKeyDown(e);
      }}
    >
      <div className="gw-title">Welcome to OpenTerm</div>
      <p className="gw-sub">A market terminal for stocks, charts, news and backtests. Pick a place to start:</p>
      <div className="gw-choices">
        {CHOICES.map((c, i) => (
          <button
            key={c.id}
            ref={i === 0 ? first : undefined}
            type="button"
            className="gw-big"
            data-testid={`welcome-${c.id}`}
            onClick={() => {
              closeWelcome();
              runCommand(c.command);
            }}
          >
            <span className="gw-big-l">{c.label}</span>
            <span className="dim">{c.hint}</span>
          </button>
        ))}
      </div>
      <div className="gw-foot">
        <button type="button" className="gw-link" data-testid="welcome-tour" onClick={startTour}>
          Take the 2-minute tour
        </button>
        <span className="pt-sp" />
        <button type="button" className="pt-b" data-testid="welcome-close" onClick={close}>
          Close (Esc)
        </button>
      </div>
    </div>
  );
}
