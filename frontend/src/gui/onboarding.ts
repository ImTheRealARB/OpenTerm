/**
 * First-run state for GUI mode: the welcome card, the tour and the banner. One small store plus three localStorage flags.
 * localStorage can be missing or throw (private window, blocked site data), so every access is wrapped in try/catch and
 * the app simply behaves as "not seen yet" / "not dismissed" without it.
 */
import { createStore } from "../state/store";
import { focusCommandLine } from "./chrome";

/** Set once the welcome card has been shown, so it appears a single time. */
export const WELCOMED_KEY = "openterm.welcomed";
/** Set when the user dismisses the "Switch to Terminal mode" banner. */
export const BANNER_KEY = "openterm.guiBanner";

export function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) !== null;
  } catch {
    return false;
  }
}

export function writeFlag(key: string): void {
  try {
    localStorage.setItem(key, "1");
  } catch {
    /* nothing to do: the flag is only a convenience */
  }
}

export interface OnboardingState {
  /** The welcome card is open. */
  welcome: boolean;
  /** Index of the tour step being shown, or null when no tour is running. */
  tour: number | null;
}

export const onboarding = createStore<OnboardingState>({ welcome: false, tour: null });

/** Opens the welcome card (first run, or "Show welcome card" in the Settings menu). Marks it as seen. */
export function showWelcome(): void {
  writeFlag(WELCOMED_KEY);
  onboarding.set((s) => ({ ...s, welcome: true, tour: null }));
}

export function closeWelcome(): void {
  onboarding.set((s) => (s.welcome ? { ...s, welcome: false } : s));
}

export function startTour(): void {
  writeFlag(WELCOMED_KEY); // someone who takes the tour does not need the card as well
  onboarding.set(() => ({ welcome: false, tour: 0 }));
}

export function tourGo(step: number, total: number): void {
  if (step < 0) return;
  if (step >= total) return endTour();
  onboarding.set((s) => ({ ...s, tour: step }));
}

export function endTour(): void {
  onboarding.set((s) => ({ ...s, tour: null }));
  focusCommandLine();
}
