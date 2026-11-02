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
    if (!readFlag(WELCOMED_KEY)) showWelcome();
    // Leaving GUI mode unmounts this: close anything still open so it is not waiting when GUI mode returns.
    return () => onboarding.set(() => ({ welcome: false, tour: null }));
  }, []);
  return (
    <>
      <Welcome />
      <Tour />
    </>
  );
}
