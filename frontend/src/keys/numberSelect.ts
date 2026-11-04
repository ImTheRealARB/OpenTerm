/**
 * Number-select for list panels: type digits, then Enter, and row N opens ("3" Enter = row 3, 1-based).
 * It is the same as moving the cursor to row 3 and pressing Enter.
 *
 * This file is the pure part (no React, no DOM) so vitest can test it. App.tsx owns the one buffer and
 * calls `numberSelectKey` for each key press, then does what the returned `kind` says.
 *
 * Which panels are skipped: a panel that handles a digit itself (BT views 1-4, GP chart ranges, ...) gets the
 * key first, so the buffer never starts there. Panels without a grid never start it either (App checks).
 */

/** Digits stay in the buffer this long; after it a digit starts a new number. */
export const NUM_TTL_MS = 3000;
/** More than 3 digits would be a typo (rows are capped well below 1000). */
export const NUM_MAX_DIGITS = 3;

export interface NumberSelectState {
  /** Digits typed so far, "" when idle. */
  buf: string;
  /** performance.now()-style time of the last digit. */
  at: number;
}

export const IDLE: NumberSelectState = { buf: "", at: 0 };

/**
 * What the caller should do:
 *  - "pass"   : not ours, handle the key as usual
 *  - "digit"  : a digit was added: show `state.buf`, swallow the key
 *  - "open"   : Enter with digits: open row `n`
 *  - "flush"  : ":" after digits ("3:GP" targets panel 3): put `text` on the command line, then let the key through
 *  - "clear"  : the buffer was dropped (Escape, Backspace to empty, any other key): swallow Escape, pass the rest
 */
export type NumberSelectOut =
  | { kind: "pass"; state: NumberSelectState }
  | { kind: "digit"; state: NumberSelectState }
  | { kind: "open"; state: NumberSelectState; n: number }
  | { kind: "flush"; state: NumberSelectState; text: string }
  | { kind: "clear"; state: NumberSelectState; swallow: boolean };

const isDigit = (k: string) => k.length === 1 && k >= "0" && k <= "9";

/** True while digits are waiting for an Enter. */
export function isLive(s: NumberSelectState, now: number): boolean {
  return s.buf !== "" && now - s.at <= NUM_TTL_MS;
}

/**
 * One key press. `startable` says whether a digit may START a number (the focused panel has a grid and did not
 * handle the digit itself); a live buffer keeps working either way.
 */
export function numberSelectKey(s: NumberSelectState, key: string, now: number, startable: boolean): NumberSelectOut {
  const live = isLive(s, now);
  if (!live) {
    // A leading 0 is never a row; a digit with no grid under it is the command line's ("3:GP").
    if (startable && isDigit(key) && key !== "0") return { kind: "digit", state: { buf: key, at: now } };
    return { kind: "pass", state: IDLE };
  }
  if (isDigit(key)) {
    if (s.buf.length >= NUM_MAX_DIGITS) return { kind: "digit", state: s }; // ignore extra digits
    return { kind: "digit", state: { buf: s.buf + key, at: now } };
  }
  if (key === "Enter") return { kind: "open", state: IDLE, n: Number(s.buf) };
  if (key === ":") return { kind: "flush", state: IDLE, text: s.buf };
  if (key === "Backspace") {
    const buf = s.buf.slice(0, -1);
    return buf ? { kind: "digit", state: { buf, at: now } } : { kind: "clear", state: IDLE, swallow: true };
  }
  if (key === "Escape") return { kind: "clear", state: IDLE, swallow: true };
  // Bare modifier keys (Shift for ":") must not drop the digits.
  if (key === "Shift" || key === "Control" || key === "Alt" || key === "Meta") return { kind: "pass", state: s };
  return { kind: "clear", state: IDLE, swallow: false };
}

/** The key presses that move a list cursor to row `n` (1-based) from anywhere: Home, then n-1 times ArrowDown. */
export function keysToRow(n: number): string[] {
  const keys = ["Home"];
  for (let i = 1; i < n; i++) keys.push("ArrowDown");
  return keys;
}
