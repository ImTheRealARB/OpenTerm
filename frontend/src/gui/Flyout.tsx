import { useLayoutEffect, useRef, type ReactNode } from "react";
import { flyoutPosition } from "../functions/categories";

/**
 * The second level of a GUI menu: a list that opens beside the row it belongs to (menu bar "Markets > Crypto",
 * sidebar "Markets > Crypto"). It sits to the right of the row, or flips to the left when the window edge is near.
 *
 * Why `position: fixed` (set in gui.css): the dropdown and the sidebar list scroll (`overflow: auto`), and a scrolling box
 * clips anything absolutely positioned inside it. A fixed box is placed against the window instead, so it is never clipped.
 *
 * Where it goes is measured once, right after it renders and before the browser paints (`useLayoutEffect`), and written
 * straight to the element's style: no second React render, so no flicker, and the rows are focusable from the first frame
 * (the keyboard opens a flyout and focuses its first row in the same tick). The maths is the pure `flyoutPosition`.
 *
 * Keyboard and mouse handling stay with the owner (MenuBar / Sidebar): this is only the box.
 */
export function Flyout({ anchor, label, className, testId, children }: { anchor: HTMLElement; label: string; className?: string; testId?: string; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = box.current!;
    const p = flyoutPosition(anchor.getBoundingClientRect(), { width: el.offsetWidth, height: el.offsetHeight }, { width: window.innerWidth, height: window.innerHeight });
    el.style.top = `${p.top}px`;
    el.style.left = `${p.left}px`;
    el.classList.toggle("flip", p.flipped);
  }, [anchor]);
  return (
    <div ref={box} className={"gm-fly" + (className ? " " + className : "")} role="menu" aria-label={label} data-testid={testId}>
      {children}
    </div>
  );
}
