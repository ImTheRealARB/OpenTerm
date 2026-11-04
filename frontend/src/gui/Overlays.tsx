import { useEffect } from "react";
import { onboarding, readFlag, showWelcome, WELCOMED_KEY } from "./onboarding";
import { Tour } from "./Tour";
import { Welcome } from "./Welcome";

/**
 * Everything GUI mode lays over the app: the first-run welcome card and the tour. Rendered only in GUI mode, so mounting
 * it is also the moment to decide whether this is the first run.
 */
export function GuiOverlays() {
  useEffect(() => {
    if (!readFlag(WELCOMED_KEY)) {
      showWelcome();
      // A new user also gets a starter layout (quotes, a chart, top news) instead of an empty grid. Loaded on demand:
      // it is only needed once per user.
      void import("./starterLayout").then((m) => m.applyStarterLayoutIfNew());
    }
    // Leaving GUI mode unmounts this: close anything still open so it is not waiting when GUI mode returns.
    return () => onboarding.set(() => ({ welcome: false, tour: null }));
  }, []);
  // The glossary tooltip (hover/focus on any [data-term]) is loaded after startup with import(), and removed when GUI mode ends.
  useEffect(() => {
    let stop: (() => void) | undefined;
    let gone = false;
    void import("./glossaryTip").then((m) => {
      if (gone) return;
      stop = m.installGlossaryTip();
    });
    return () => {
      gone = true;
      stop?.();
    };
  }, []);
  return (
    <>
      <Welcome />
      <Tour />
    </>
  );
}
