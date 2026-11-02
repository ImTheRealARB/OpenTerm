import { useMemo, useRef, useState } from "react";
import { FUNCTION_LIST, isFunction } from "../functions/registry";
import { CATEGORIES, categoryOf, groupByCategory, type Category } from "../functions/categories";
import { chromeKeyDown, moveFocus } from "./chrome";
import { runCommand } from "./run";
import { searchFunctions, sidebarEnter } from "./search";

type Def = (typeof FUNCTION_LIST)[number];

/** Groups open when the sidebar first shows; the rest start collapsed so the list is not 100 rows long. */
const OPEN_AT_START: readonly Category[] = ["Markets", "Charts"];

/**
 * GUI sidebar: every registered function grouped by category, with a search box that does the same job as the
 * command line. Typing filters the list (code or title); Enter runs the typed command, or the top match for a loose
 * word (see `sidebarEnter`). Clicking a row runs that function in the focused panel. Groups collapse and expand.
 */
export function Sidebar() {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<ReadonlySet<Category>>(() => new Set(CATEGORIES.filter((c) => !OPEN_AT_START.includes(c))));
  const root = useRef<HTMLElement>(null);
  const groups = useMemo(() => groupByCategory(FUNCTION_LIST), []);
  const matches = useMemo(() => searchFunctions(query, FUNCTION_LIST), [query]);
  const searching = query.trim() !== "";

  const toggle = (c: Category) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(c)) next.add(c);
      return next;
    });

  const row = (f: Def, i: number) => (
    <button
      key={f.code}
      type="button"
      className={"gs-item" + (f.load ? "" : " dim") + (searching && i === 0 ? " top" : "")}
      title={f.title}
      data-code={f.code}
      onClick={() => runCommand(f.code)}
    >
      <span className="gs-code">{f.code}</span>
      <span className="gs-title">{f.title}</span>
    </button>
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLElement>) => {
    if (!e.ctrlKey && !e.altKey && !e.metaKey) {
      // Arrow keys walk the focusable rows (search box, group headers, function rows) in order.
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        moveFocus(root.current!, ".gs-search, .gs-head, .gs-item", e.key === "ArrowDown" ? 1 : -1);
      }
    }
    chromeKeyDown(e);
  };

  return (
    <aside className="gs" ref={root} data-testid="gui-sidebar" aria-label="Functions" onKeyDown={onKeyDown}>
      <input
        className="gs-search"
        data-testid="gui-search"
        type="text"
        spellCheck={false}
        autoComplete="off"
        placeholder="Search or type a command"
        aria-label="Search functions, or type a command and press Enter"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== "Enter" || e.ctrlKey || e.altKey || e.metaKey) return;
          e.preventDefault();
          const cmd = sidebarEnter(query, matches[0], isFunction);
          // Clear the box only when the command ran (a failed one keeps its text and the error shows in the top bar).
          if (cmd !== null && runCommand(cmd)) setQuery("");
        }}
      />
      <div className="gs-list">
        {searching ? (
          matches.length ? (
            matches.map((f, i) => (
              <div key={f.code} className="gs-hit">
                {row(f, i)}
                <span className="gs-cat dim">{categoryOf(f.code)}</span>
              </div>
            ))
          ) : (
            <div className="gs-empty dim">No function matches. Enter runs it as a command.</div>
          )
        ) : (
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
        )}
      </div>
    </aside>
  );
}
