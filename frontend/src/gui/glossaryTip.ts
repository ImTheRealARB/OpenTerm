/**
 * The glossary tooltip: ONE delegated listener on `document` instead of wrapping every label.
 * Any element with `data-term="EPS"` shows the glossary line in a small box when the mouse is over it or it has
 * keyboard focus (the element needs `tabindex="0"` to be focusable; GUI-mode labels get it from `termProps`).
 * It only does anything while `<html data-mode="gui">`, so Terminal mode never shows a tooltip.
 * Loaded lazily by the GUI shell (`Overlays.tsx`); the glossary text itself comes in with it.
 */
import { explain } from "./glossary";

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
    // Place it just under the term, and keep it inside the window.
    const r = el.getBoundingClientRect();
    const w = tip.offsetWidth;
    tip.style.left = `${Math.max(4, Math.min(r.left, window.innerWidth - w - 4))}px`;
    const below = r.bottom + 4;
    tip.style.top = `${below + tip.offsetHeight > window.innerHeight ? Math.max(4, r.top - tip.offsetHeight - 4) : below}px`;
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
