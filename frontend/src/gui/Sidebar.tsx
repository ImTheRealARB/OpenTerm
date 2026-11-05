import { useMemo, useRef, useState } from "react";
import { FUNCTION_LIST } from "../functions/registry";
import { CATEGORIES, groupByCategory, type Category } from "../functions/categories";
import { chromeKeyDown, moveFocus } from "./chrome";
import { runCommand } from "./run";
import { useSidebarHidden } from "./sidebarState";
import { shortTitle } from "./titleText";

type Def = (typeof FUNCTION_LIST)[number];

/** Groups open when the sidebar first shows; the rest start collapsed so the list is not 100 rows long. */
const OPEN_AT_START: readonly Category[] = [];

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

/**
 * GUI sidebar: "Start here" tasks, then every registered function grouped by category. Clicking a row runs that function in
 * the focused panel. Groups collapse and expand. There is no search box here: the command line already finds functions and
 * companies by plain words ("chart", "tesla"), so a second box only made beginners choose between two.
 */
export function Sidebar() {
  // A wrapper, so the hooks inside SidebarPanel always run in the same order (it simply is not mounted while hidden).
  return useSidebarHidden() ? null : <SidebarPanel />;
}

function SidebarPanel() {
  const [collapsed, setCollapsed] = useState<ReadonlySet<Category>>(() => new Set(CATEGORIES.filter((c) => !OPEN_AT_START.includes(c))));
  const root = useRef<HTMLElement>(null);
  const groups = useMemo(() => groupByCategory(FUNCTION_LIST), []);

  const toggle = (c: Category) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(c)) next.add(c);
      return next;
    });

  const row = (f: Def) => (
    <button
      key={f.code}
      type="button"
      className={"gs-item" + (f.load ? "" : " dim")}
      title={f.title}
      data-code={f.code}
      onClick={() => runCommand(f.code)}
    >
      <span className="gs-code">{f.code}</span>
      <span className="gs-title">{shortTitle(f.title)}</span>
    </button>
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLElement>) => {
    if (!e.ctrlKey && !e.altKey && !e.metaKey) {
      // Arrow keys walk the focusable rows (Start-here tasks, group headers, function rows) in order.
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        moveFocus(root.current!, ".gs-task, .gs-head, .gs-item", e.key === "ArrowDown" ? 1 : -1);
      }
    }
    chromeKeyDown(e);
  };

  return (
    <aside className="gs" ref={root} data-testid="gui-sidebar" aria-label="Functions" onKeyDown={onKeyDown}>
      <div className="gs-list">
        {
          // Not a ".gs-head": the category headers are counted by the shell test, and this group is always open.
          <section className="gs-start" data-testid="start-here" aria-label="Start here">
            <div className="gs-start-title">Start here</div>
            {START_HERE.map((t) => (
              <button key={t.label} type="button" className="gs-task" onClick={() => runCommand(t.text)}>
                <span>{t.label}</span>
                <small>{t.code}</small>
              </button>
            ))}
          </section>
        }
        {
          groups.map((g) => {
            const isOpen = !collapsed.has(g.category);
            return (
              <section key={g.category} className="gs-group">
                <button type="button" className="gs-head" aria-expanded={isOpen} onClick={() => toggle(g.category)}>
                  <span className="gs-caret" aria-hidden="true">{isOpen ? "-" : "+"}</span>
                  {g.category}
                  <span className="dim"> {g.items.length}</span>
                </button>
                {isOpen && g.items.map(row)}
              </section>
            );
          })
        }
      </div>
    </aside>
  );
}
