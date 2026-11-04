/**
 * The glossary tooltip: ONE delegated listener on `document` instead of wrapping every label.
 * Any element with `data-term="EPS"` shows the glossary line in a small box when the mouse is over it or it has
 * keyboard focus (the element needs `tabindex="0"` to be focusable; GUI-mode labels get it from `termProps`).
 * It only does anything while `<html data-mode="gui">`, so Terminal mode never shows a tooltip.
 * Loaded lazily by the GUI shell (`Overlays.tsx`); the glossary text itself comes in with it.
 */
import { explain } from "./glossary";

export interface Box { left: number; top: number; right: number; bottom: number }

/**
 * Where to put the tooltip so it does not cover the row it explains (pure, unit-tested).
 * Preference: beside the panel that holds the term (right, then left), top lined up with the term.
 * Fallback when the panel fills the window: below the term, or above it when there is no room below.
 * `anchor` is the term, `area` the panel (or the window), `view` the window size.
 */
export function placeTip(anchor: Box, area: Box, w: number, h: number, vw: number, vh: number): { left: number; top: number } {
  const clampTop = (t: number) => Math.max(4, Math.min(t, vh - h - 4));
  if (area.right + 6 + w <= vw - 4) return { left: area.right + 6, top: clampTop(anchor.top) };
  if (area.left - 6 - w >= 4) return { left: area.left - 6 - w, top: clampTop(anchor.top) };
  const left = Math.max(4, Math.min(anchor.left, vw - w - 4));
  const below = anchor.bottom + 4;
  return { left, top: below + h > vh ? Math.max(4, anchor.top - h - 4) : below };
}

/** Starts listening; returns a function that stops and removes any open tooltip. */
export function installGlossaryTip(): () => void {
  let tip: HTMLDivElement | null = null;

  const hide = () => {
    tip?.remove();
    tip = null;
  };

  const show = (el: Element) => {
    if (document.documentElement.dataset.mode !== "gui") return;
    const term = el.getAttribute("data-term") ?? "";
    const line = explain(term);
    if (!line) return;
    hide();
    tip = document.createElement("div");
    tip.className = "gl-tip";
    tip.setAttribute("role", "tooltip");
    tip.textContent = `${term.toUpperCase()}: ${line}`;
    document.body.appendChild(tip);
    // Place it beside the panel (see placeTip) so it never hides the values being explained.
    const panel = el.closest(".panel") ?? el;
    const pos = placeTip(el.getBoundingClientRect(), panel.getBoundingClientRect(), tip.offsetWidth, tip.offsetHeight, window.innerWidth, window.innerHeight);
    tip.style.left = `${pos.left}px`;
    tip.style.top = `${pos.top}px`;
  };

  const termOf = (t: EventTarget | null) => (t instanceof Element ? t.closest("[data-term]") : null);
  const over = (e: Event) => {
    const el = termOf(e.target);
    if (el) show(el);
  };
  const out = (e: Event) => {
    if (termOf(e.target)) hide();
  };
  const key = (e: KeyboardEvent) => {
    if (e.key === "Escape") hide(); // Esc closes it (it still goes on to its normal job)
  };

  document.addEventListener("mouseover", over);
  document.addEventListener("mouseout", out);
  document.addEventListener("focusin", over);
  document.addEventListener("focusout", out);
  document.addEventListener("keydown", key);
  return () => {
    document.removeEventListener("mouseover", over);
    document.removeEventListener("mouseout", out);
    document.removeEventListener("focusin", over);
    document.removeEventListener("focusout", out);
    document.removeEventListener("keydown", key);
    hide();
  };
}
