import "./Tour.css"; // this component's GUI-only rules, loaded with its chunk
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useStore } from "../state/store";
import { chromeKeyDown } from "./chrome";
import { endTour, onboarding, tourGo } from "./onboarding";
import { effectiveBindings } from "../keys/keys";
import { TOUR_STEPS, tourText } from "./tourSteps";

interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Finds the first selector that matches a visible element and returns its rectangle in viewport coordinates. */
function targetBox(selectors: string[]): Box | null {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return { left: r.left, top: r.top, width: r.width, height: r.height };
  }
  return null;
}

/**
 * The guided tour: a solid 2px outline around one piece of the screen and a small caption with Back / Next / Done.
 * No animation. Esc ends it. The outline is a separate fixed-position box that ignores the mouse (`pointer-events: none`),
 * so the page underneath is never changed or blocked.
 */
export function Tour() {
  const step = useStore(onboarding, (s) => s.tour);
  const [box, setBox] = useState<Box | null>(null);
  const next = useRef<HTMLButtonElement>(null);

  // Measure the target whenever the step changes or the window is resized.
  useLayoutEffect(() => {
    if (step === null) return;
    const measure = () => setBox(targetBox(TOUR_STEPS[step].selectors));
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [step]);

  // Keep the keyboard on the caption's Next button, so Enter advances and Esc ends.
  useEffect(() => {
    if (step !== null) next.current?.focus();
  }, [step]);

  if (step === null) return null;
  const s = TOUR_STEPS[step];
  const last = step === TOUR_STEPS.length - 1;
  // The caption goes below the target, or near the top-left corner when there is no target. Clamped so it stays on screen.
  const W = 320;
  const cap = box
    ? { left: Math.max(8, Math.min(window.innerWidth - W - 8, box.left)), top: Math.min(window.innerHeight - 150, box.top + box.height + 10) }
    : { left: 24, top: 80 };
  return (
    <>
      {box && <div className="gt-ring" data-testid="tour-ring" style={{ left: box.left - 2, top: box.top - 2, width: box.width + 4, height: box.height + 4 }} />}
      <div
        className="gt-cap"
        data-testid="tour-caption"
        role="dialog"
        aria-label={`Tour step ${step + 1} of ${TOUR_STEPS.length}`}
        style={{ left: cap.left, top: cap.top, width: W }}
        onKeyDown={(e) => {
          if (e.ctrlKey || e.altKey || e.metaKey) return;
          if (e.key === "Escape") {
            e.stopPropagation();
            e.preventDefault();
            endTour();
            return;
          }
          chromeKeyDown(e);
        }}
      >
        <div className="gt-n">
          STEP {step + 1} OF {TOUR_STEPS.length}
        </div>
        <div className="gt-t">{s.title}</div>
        <div>{tourText(s, effectiveBindings())}</div>
        <div className="gt-btns">
          <button type="button" className="pt-b" data-testid="tour-back" disabled={step === 0} onClick={() => tourGo(step - 1, TOUR_STEPS.length)}>
            Back
          </button>
          <button ref={next} type="button" className="pt-b gt-next" data-testid="tour-next" onClick={() => (last ? endTour() : tourGo(step + 1, TOUR_STEPS.length))}>
            {last ? "Done" : "Next"}
          </button>
          <span className="pt-sp" />
          <span className="dim">Esc ends the tour</span>
        </div>
      </div>
    </>
  );
}
