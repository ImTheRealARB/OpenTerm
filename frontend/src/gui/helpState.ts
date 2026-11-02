/**
 * State of the right-hand help drawer ("?" on a panel, or Alt+H). It remembers which element had focus when it
 * opened, so closing it (Esc or the Close button) puts the keyboard back where the user was.
 */
import { createStore } from "../state/store";
import { focusCommandLine } from "./chrome";

export const helpDrawer = createStore<{ panel: number } | null>(null);

let returnTo: HTMLElement | null = null;

export function openHelp(panel: number, from: Element | null = document.activeElement): void {
  returnTo = from instanceof HTMLElement ? from : null;
  helpDrawer.set(() => ({ panel }));
}

export function closeHelp(): void {
  helpDrawer.set(() => null);
  // The element may be gone (the panel re-rendered); then the command line is the safe place to land.
  if (returnTo?.isConnected) returnTo.focus();
  else focusCommandLine();
  returnTo = null;
}

export function toggleHelp(panel: number): void {
  if (helpDrawer.get()) closeHelp();
  else openHelp(panel);
}
