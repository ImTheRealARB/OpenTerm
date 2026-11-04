import { useEffect, useMemo, useRef, useState } from "react";
import { FUNCTION_LIST } from "../functions/registry";
import { CATEGORIES, groupByCategory, type Category } from "../functions/categories";
import { setMode } from "../settings/runtime";
import { chromeKeyDown, focusCommandLine, moveFocus } from "./chrome";
import { runCommand } from "./run";
import { showWelcome, startTour } from "./onboarding";
import { SymbolPicker } from "./SymbolPicker";
import { TEMPLATE_INFO } from "./templateMenu";

/** One row of a dropdown: a function, or one of the extra entries under Settings (switch mode, tour, welcome card). */
type Entry =
  | { kind: "fn"; code: string; title: string; built: boolean; run?: string }
  | { kind: "terminal" }
  | { kind: "tour" }
  | { kind: "welcome" };

/**
 * GUI menu bar: the seven categories, each opening a dropdown of its functions, plus the symbol box on the right.
 *
 * Mouse: click a category to open it, hover another while one is open to switch, click a function to run it.
 * Keyboard: Tab reaches the categories; Enter / Space / ArrowDown open one and focus its first item; ArrowUp / ArrowDown
 * move inside a dropdown, ArrowLeft / ArrowRight move between categories; Enter runs the item; Esc closes and returns
 * focus to the command line. Picking a function runs it in the focused panel through `runCommand` (= the command line's `execute`).
 */
export function MenuBar() {
  const [open, setOpen] = useState<Category | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  // Set when a menu was opened from the keyboard, so the effect below moves focus into it (a mouse open must not steal focus).
  const focusOnOpen = useRef(false);
  const groups = useMemo(() => groupByCategory(FUNCTION_LIST), []);

  const entries = (c: Category): Entry[] => {
    const list: Entry[] = (groups.find((g) => g.category === c)?.items ?? []).map((f) => ({ kind: "fn", code: f.code, title: f.title, built: !!f.load }));
    if (c === "Settings") list.push(...TEMPLATE_INFO.map((t) => ({ kind: "fn" as const, code: "TMPL", title: "Template: " + t.label, built: true, run: "TMPL " + t.id })), { kind: "terminal" }, { kind: "tour" }, { kind: "welcome" });
    return list;
  };

  // Move focus into a keyboard-opened dropdown.
  useEffect(() => {
    if (open && focusOnOpen.current) bar.current?.querySelector<HTMLElement>(".gm-item")?.focus();
    focusOnOpen.current = false;
  }, [open]);

  // Click anywhere outside the bar closes an open menu.
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!bar.current?.contains(e.target as Node)) setOpen(null);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  const pick = (e: Entry) => {
    setOpen(null);
    if (e.kind === "terminal") {
      setMode("terminal");
      focusCommandLine();
    } else if (e.kind === "tour") startTour();
    else if (e.kind === "welcome") showWelcome();
    else runCommand(e.run ?? e.code);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return; // chords bubble (chromeKeyDown would also ignore them)
    const el = e.target as HTMLElement;
    const onCategory = el.classList.contains("gm-cat");
    const onItem = el.classList.contains("gm-item");
    if (e.key === "Escape") setOpen(null);
    else if (onCategory && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      focusOnOpen.current = true;
      setOpen(el.dataset.cat as Category);
    } else if (onCategory && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
      e.preventDefault();
      moveFocus(bar.current!, ".gm-cat", e.key === "ArrowRight" ? 1 : -1);
      // With a menu open, the new category's menu opens too (like a desktop menu bar).
      if (open) setOpen((document.activeElement as HTMLElement).dataset.cat as Category);
    } else if (onItem && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      moveFocus(bar.current!, ".gm-item", e.key === "ArrowDown" ? 1 : -1);
    } else if (onItem && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
      e.preventDefault();
      const cats = Array.from(bar.current!.querySelectorAll<HTMLElement>(".gm-cat"));
      const i = CATEGORIES.indexOf(open!);
      const next = cats[(i + (e.key === "ArrowRight" ? 1 : -1) + cats.length) % cats.length];
      focusOnOpen.current = true;
      setOpen(next.dataset.cat as Category);
      next.focus();
    } else if (onItem && (e.key === "Home" || e.key === "End")) {
      e.preventDefault();
      const items = bar.current!.querySelectorAll<HTMLElement>(".gm-item");
      items[e.key === "Home" ? 0 : items.length - 1]?.focus();
    }
    chromeKeyDown(e);
  };

  return (
    <div className="gm-bar" ref={bar} role="menubar" data-testid="gui-menubar" onKeyDown={onKeyDown}>
      {CATEGORIES.map((c) => (
        <div key={c} className="gm-slot">
          <button
            type="button"
            role="menuitem"
            aria-haspopup="menu"
            aria-expanded={open === c}
            className={"gm-cat" + (open === c ? " on" : "")}
            data-cat={c}
            onClick={(e) => {
              // detail === 0 means the click came from Enter / Space, not a mouse: then focus the first item.
              focusOnOpen.current = e.detail === 0 && open !== c;
              setOpen(open === c ? null : c);
            }}
            onMouseEnter={() => open && setOpen(c)}
          >
            {c}
          </button>
          {open === c && (
            <div className="gm-drop" role="menu" aria-label={c}>
              {entries(c).map((en) =>
                en.kind !== "fn" ? (
                  <button key={en.kind} type="button" role="menuitem" className={"gm-item" + (en.kind === "terminal" ? " gm-sep" : "")} onClick={() => pick(en)}>
                    <span className="gm-code">{en.kind === "terminal" ? "MODE" : "HELP"}</span>
                    <span>{en.kind === "terminal" ? "Switch to Terminal mode" : en.kind === "tour" ? "Take the tour" : "Show welcome card"}</span>
                  </button>
                ) : (
                  <button key={en.code} type="button" role="menuitem" className={"gm-item" + (en.built ? "" : " dim")} data-template={en.run?.slice(5)} onClick={() => pick(en)}>
                    <span className="gm-code">{en.code}</span>
                    <span>{en.title}</span>
                  </button>
                ),
              )}
            </div>
          )}
        </div>
      ))}
      <span className="gm-fill" />
      <SymbolPicker />
    </div>
  );
}
