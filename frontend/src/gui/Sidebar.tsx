import { useEffect, useMemo, useRef, useState } from "react";
import { FUNCTION_LIST } from "../functions/registry";
import { CATEGORIES, menuOf, type Category } from "../functions/categories";
import { chromeKeyDown, moveFocus } from "./chrome";
import { Flyout } from "./Flyout";
import { runCommand } from "./run";
import { useSidebarHidden } from "./sidebarState";
import { shortTitle } from "./titleText";

type Def = (typeof FUNCTION_LIST)[number];

/**
 * "Start here": the everyday tasks in plain words, each one click. `text` is ordinary command-line text (run by
 * `runCommand`, like every GUI control); `code` is shown small and grey as a learning aid, never on its own.
 *  - "Stock chart" runs GP on the panel's current security (the "sticky" one from your last lookup).
 *  - "Top news" is `N TOP`, explicit, because a bare `N` after a stock lookup shows THAT stock's news.
 *  - The watchlist and portfolio get default names so the first click needs no typing.
 */
const START_HERE: readonly { label: string; code: string; text: string }[] = [
  { label: "Stock chart", code: "GP", text: "GP" },
  { label: "My watchlist", code: "WL", text: "WL MY-STOCKS" },
  { label: "Top news", code: "N", text: "N TOP" },
  { label: "World markets", code: "WEI", text: "WEI" },
  { label: "My portfolio", code: "PORT", text: "PORT MAIN" },
  { label: "Try a backtest", code: "BT", text: "BT" },
];

/** The group whose flyout is open, and the row it hangs from. */
type OpenSub = { category: Category; name: string; row: HTMLElement };

/**
 * GUI sidebar: "Start here" tasks, then the seven categories (collapsed at first, so the list is short). An open category
 * shows its functions directly when it is short (Charts, News ...), or its plain-word groups ("Crypto", "Options") when it is
 * long; a group opens a flyout beside the sidebar with its functions, the same two levels as the menu bar (`categories.ts`).
 * There is no search box here: the command line already finds functions and companies by plain words ("chart", "tesla").
 *
 * Mouse: click a category to open or close it; click a group to open its flyout (while one is open, hovering another group
 * switches to it); click a function to run it. A click anywhere else closes the flyout.
 * Keyboard: ArrowUp / ArrowDown walk the sidebar's rows; Enter / Space / ArrowRight on a group open its flyout and focus it;
 * in the flyout ArrowUp / ArrowDown move, ArrowLeft or Esc go back to the group row.
 */
export function Sidebar() {
  // A wrapper, so the hooks inside SidebarPanel always run in the same order (it simply is not mounted while hidden).
  return useSidebarHidden() ? null : <SidebarPanel />;
}

function SidebarPanel() {
  const [collapsed, setCollapsed] = useState<ReadonlySet<Category>>(() => new Set(CATEGORIES));
  const [sub, setSub] = useState<OpenSub | null>(null);
  const root = useRef<HTMLElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const focusOnSub = useRef(false);
  const menus = useMemo(() => CATEGORIES.map((c) => ({ category: c, groups: menuOf(c, FUNCTION_LIST) })), []);

  const toggle = (c: Category) => {
    if (sub?.category === c) setSub(null); // closing a category closes its flyout
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(c)) next.add(c);
      return next;
    });
  };

  // Keyboard-opened flyout: focus its first row.
  useEffect(() => {
    if (sub && focusOnSub.current) root.current?.querySelector<HTMLElement>(".gm-fly .gs-item")?.focus();
    focusOnSub.current = false;
  }, [sub]);

  // A click outside the sidebar closes the flyout (the flyout is inside the sidebar's DOM, so clicks on it count as inside).
  useEffect(() => {
    if (!sub) return;
    const close = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setSub(null);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [sub]);

  const run = (code: string) => {
    setSub(null);
    runCommand(code);
  };

  const row = (f: Def) => (
    <button key={f.code} type="button" className={"gs-item" + (f.load ? "" : " dim")} title={f.title} data-code={f.code} onClick={() => run(f.code)}>
      <span className="gs-code">{f.code}</span>
      <span className="gs-title">{shortTitle(f.title)}</span>
    </button>
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLElement>) => {
    if (!e.ctrlKey && !e.altKey && !e.metaKey) {
      const el = e.target as HTMLElement;
      const fly = el.closest<HTMLElement>(".gm-fly");
      if (fly && sub && (e.key === "Escape" || e.key === "ArrowLeft")) {
        // Close only the flyout and go back to its group row (Esc must not leave the sidebar).
        e.preventDefault();
        e.stopPropagation();
        const back = sub.row;
        setSub(null);
        back.focus();
        return;
      }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        // In the flyout: its rows. Otherwise the sidebar's own rows (Start-here tasks, category headers, groups, functions).
        e.preventDefault();
        if (fly) moveFocus(fly, ".gs-item", e.key === "ArrowDown" ? 1 : -1);
        else moveFocus(list.current!, ".gs-task, .gs-head, .gs-sub, .gs-item", e.key === "ArrowDown" ? 1 : -1);
      } else if (e.key === "ArrowRight" && el.dataset.group) {
        e.preventDefault();
        focusOnSub.current = true;
        setSub({ category: el.dataset.cat as Category, name: el.dataset.group, row: el });
      }
    }
    chromeKeyDown(e);
  };

  const open = sub && menus.find((m) => m.category === sub.category)?.groups.find((g) => g.name === sub.name);

  return (
    <aside className="gs" ref={root} data-testid="gui-sidebar" aria-label="Functions" onKeyDown={onKeyDown}>
      <div className="gs-list" ref={list} onScroll={() => sub && setSub(null)}>
        {/* Not a ".gs-head": the category headers are counted by the shell test, and this group is always open. */}
        <section className="gs-start" data-testid="start-here" aria-label="Start here">
          <div className="gs-start-title">Start here</div>
          {START_HERE.map((t) => (
            <button key={t.label} type="button" className="gs-task" onClick={() => run(t.text)}>
              <span>{t.label}</span>
              <small>{t.code}</small>
            </button>
          ))}
        </section>
        {menus.map(({ category, groups }) => {
          const isOpen = !collapsed.has(category);
          return (
            <section key={category} className="gs-group">
              <button type="button" className="gs-head" aria-expanded={isOpen} onClick={() => toggle(category)}>
                <span className="gs-caret" aria-hidden="true">{isOpen ? "-" : "+"}</span>
                {category}
              </button>
              {isOpen &&
                (groups.length === 1
                  ? groups[0].items.map(row)
                  : groups.map((g) => {
                      const on = sub?.category === category && sub.name === g.name;
                      return (
                        <button
                          key={g.name}
                          type="button"
                          className={"gs-sub" + (on ? " on" : "")}
                          aria-haspopup="menu"
                          aria-expanded={on}
                          data-cat={category}
                          data-group={g.name}
                          onClick={(e) => {
                            focusOnSub.current = e.detail === 0; // Enter / Space: move focus into the flyout
                            setSub(on ? null : { category, name: g.name, row: e.currentTarget });
                          }}
                          // Once a flyout is open, pointing at another group switches to it (like a desktop menu).
                          onMouseEnter={(e) => sub && !on && setSub({ category, name: g.name, row: e.currentTarget })}
                        >
                          <span>{g.name}</span>
                          <span className="gm-arrow" aria-hidden="true">›</span>
                        </button>
                      );
                    }))}
            </section>
          );
        })}
      </div>
      {/* Outside the scrolling list, so the sidebar's own ArrowUp / ArrowDown never walk into it. */}
      {sub && open && (
        <Flyout key={sub.category + sub.name} anchor={sub.row} label={sub.name} className="gs-fly" testId="gs-flyout">
          {open.items.map(row)}
        </Flyout>
      )}
    </aside>
  );
}
