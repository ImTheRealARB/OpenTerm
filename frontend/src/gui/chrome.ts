/**
 * Shared behaviour for every GUI control (menu bar, sidebar, mode toggle).
 *
 * The app has global keys on `window` (App.tsx): Tab cycles panels, plain letters go to the focused panel or start a
 * command, Enter/arrows can be panel keys. A GUI control that has focus must not lose its own keys to those, but it must
 * not swallow the chords either (Ctrl+K "focus command line", Alt+G "toggle mode", ...). So:
 *   - Ctrl / Alt / Meta chords: left alone, they bubble up to the global handler (the "Ctrl+K gotcha" from CLAUDE.md).
 *   - Tab / Shift+Tab: kept inside (the browser's own focus move runs, we just stop App's "next panel" from taking it).
 *   - Escape: always returns focus to the command line (the way back to the keyboard-first workflow).
 *   - every other plain key: stays inside the control (so typing in the search box never reaches panel keys).
 */
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { commandInputRef } from "../components/CommandLine";

/** Focus goes back to the command line, as after a command in terminal mode. */
export function focusCommandLine(): void {
  commandInputRef.current?.focus();
}

/** Attach as `onKeyDown` on a GUI control's root. Returns true when the key was Escape (so the caller can close menus). */
export function chromeKeyDown(e: ReactKeyboardEvent): boolean {
  if (e.ctrlKey || e.altKey || e.metaKey) return false; // chords bubble to the global handler
  if (e.key === "Escape") {
    e.stopPropagation();
    e.preventDefault();
    focusCommandLine();
    return true;
  }
  // Tab and everything else: stop App's window-level handler from seeing it. We do NOT preventDefault, so Tab still moves focus
  // and Enter / Space still click the focused button.
  e.stopPropagation();
  return false;
}

/** Moves focus to the next / previous element matching `selector` inside `root` (wraps at the ends). */
export function moveFocus(root: HTMLElement, selector: string, delta: 1 | -1): void {
  const els = Array.from(root.querySelectorAll<HTMLElement>(selector));
  if (!els.length) return;
  const i = els.indexOf(document.activeElement as HTMLElement);
  const next = i < 0 ? (delta === 1 ? 0 : els.length - 1) : (i + delta + els.length) % els.length;
  els[next].focus();
}
